"""scenes/exhibit_lod.py — LOD debug visualiser (v2).

A standalone exhibit scene that demonstrates dual-resolution simulation
with **real portal transitions**.

Layout:
    ┌─────────────────────────────┬────────────────────┐
    │   ACTIVE ZONE               │   OFF-SCREEN ZONE  │
    │   rendered at real TILE_SIZE │   coarse tile grid  │
    │   camera follows player     │   A* paths shown    │
    │   WASD movement + physics   │   vision cones      │
    │                             │                     │
    ├─────────────────────────────┴────────────────────┤
    │  Status bar: zone counts, tick info, entity stats │
    ├──────────────────────────────────────────────────┤
    │  Event log                                        │
    └──────────────────────────────────────────────────┘

Key improvements (v2):
    - **Portal transitions**: player walks through portals with fade —
      arriving zone's NPCs promote, departing zone's NPCs demote.
    - **Portal-bounce prevention**: cooldown after transition.
    - **A* path rendering**: off-screen NPC paths drawn on minimap.
    - **No Tab zone-cycle** — only real portal traversal changes zones.

Controls:
    WASD   Move the player (in the active zone)
    1-6    Select which off-screen zone to view in the right panel
    Space  Spawn a test NPC in the RIGHT panel zone
    P      Pause/unpause the off-screen sim
    +/-    Adjust sim tick rate
    V      Toggle NPC vision overlay on minimap
    Esc    Exit exhibit

Launch from the game with F6 or standalone:
    ``python -c "from scenes.exhibit_lod import run_exhibit; run_exhibit()"``
"""

from __future__ import annotations

import random
import pygame

from core.app import App
from core.constants import TILE_SIZE
from core.tiles import TILE_COLORS, SOLID_IDS
from core.scene import Scene
from core.ecs import World
from core.zones import list_zones
from core.types import Direction, EntityKind
from components import (
    Position, Velocity, Sprite, Identity, Facing, Collider,
    Health, CoarsePos, Timers, Player, Camera, GameClock,
    TileEntity,
)
from systems.zone_sim import ZoneSim
from systems.lod import promote, demote, sync_zone_lod, tick_timers
from systems.physics import movement_system


# ── Colours ───────────────────────────────────────────────────────────
COL_BG       = (12, 12, 16)
COL_PANEL_BG = (18, 18, 24)
COL_GRID     = (30, 30, 40)
COL_DIVIDER  = (50, 50, 65)
COL_TEXT     = (180, 180, 180)
COL_DIM      = (100, 110, 105)
COL_ACCENT   = (255, 200, 80)
COL_PROMOTE  = (80, 255, 120)
COL_DEMOTE   = (255, 100, 80)
COL_NPC      = (100, 180, 255)
COL_PORTAL   = (255, 180, 50)
COL_PLAYER   = (255, 255, 100)
COL_COARSE_NPC = (70, 140, 220)
COL_COARSE_BG  = (22, 22, 30)

# Layout constants (960x640 screen)
LEFT_W   = 580
RIGHT_W  = 960 - LEFT_W  # 380
STATUS_H = 48
LOG_H    = 64


class ExhibitLOD(Scene):
    """Debug exhibit: dual-resolution zone simulation with portal transitions."""

    def __init__(self) -> None:
        self.world = World()
        self.zone_sim = ZoneSim(self.world, tick_interval=1.0)
        self.active_zone: str = ""
        self.viewed_zone: str = ""
        self.available_zones: list[str] = []
        self.paused: bool = False
        self.total_ticks: int = 0
        self.log: list[str] = []
        self._next_npc_id: int = 0
        self._flash_timer: float = 0.0
        self._flash_text: str = ""
        self._flash_color: tuple[int, int, int] = COL_TEXT
        # Active zone tile/portal cache (for physics)
        self._active_tiles: list[list[int]] = []
        self._portal_positions: set[tuple[int, int]] = set()
        # Portal transition state
        self._fade_alpha: float = 0.0
        self._fade_dir: int = 0          # 0=idle, 1=out, -1=in
        self._fade_speed: float = 3.0    # alpha per second
        self._pending_tp: tuple[str, int, int] | None = None
        self._portal_arrival: tuple[int, int] | None = None  # bounce suppress
        # Vision overlay toggle
        self._show_vision: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: App) -> None:
        self.available_zones = sorted(list_zones())
        if not self.available_zones:
            self._log("No zones found!")
            return

        for name in self.available_zones:
            self.zone_sim.load_zone(name)

        # Default: first zone with outdoor space (playground) or first
        self.active_zone = ("playground" if "playground" in self.available_zones
                            else self.available_zones[0])
        self.viewed_zone = self._pick_viewed_default()

        self._cache_active_zone()
        self.world.resources.set(Camera())
        self.world.resources.set(GameClock())

        # Spawn player
        self._spawn_player()

        # Spawn test NPCs in every zone
        for zn in self.available_zones:
            self._spawn_test_npcs(zn, count=2)

        # Promote NPCs in the active zone
        sync_zone_lod(self.world, self.active_zone)

        self._log(f"Exhibit started -- active={self.active_zone}")
        self._log(f"Zones: {', '.join(self.available_zones)}")

    def _pick_viewed_default(self) -> str:
        """Pick a default right-panel zone (first zone != active)."""
        for zn in self.available_zones:
            if zn != self.active_zone:
                return zn
        return self.active_zone

    def _spawn_player(self) -> None:
        """Spawn the player entity at the centre of the active zone."""
        zc = self.zone_sim.get_zone(self.active_zone)
        if zc is None:
            return
        mid_r = zc.height // 2
        mid_c = zc.width // 2
        eid = self.world.spawn()
        self.world.add(eid, Position(
            x=float(mid_c) + 0.5,
            y=float(mid_r) + 0.5,
            zone=self.active_zone,
        ))
        self.world.add(eid, CoarsePos(
            row=mid_r, col=mid_c, zone=self.active_zone,
        ))
        self.world.add(eid, Sprite(char="@", color=COL_PLAYER, layer=10))
        self.world.add(eid, Identity(name="Player", kind=EntityKind.PLAYER))
        self.world.add(eid, Player(speed=6.0))
        self.world.add(eid, Velocity())
        self.world.add(eid, Facing())
        self.world.add(eid, Collider())

    def _cache_active_zone(self) -> None:
        """Cache tile data for the active zone (needed by physics)."""
        zc = self.zone_sim.get_zone(self.active_zone)
        if zc:
            self._active_tiles = zc.tiles
            self._portal_positions = set(zc.portals.keys())
        else:
            self._active_tiles = []
            self._portal_positions = set()

    # ── NPC spawning ──────────────────────────────────────────────

    def _spawn_test_npcs(self, zone_name: str, count: int = 1) -> None:
        """Spawn test NPCs with CoarsePos in the given zone."""
        zc = self.zone_sim.get_zone(zone_name)
        if zc is None:
            return

        walkable: list[tuple[int, int]] = []
        for r in range(1, zc.height - 1):
            for c in range(1, zc.width - 1):
                if zc.tiles[r][c] not in SOLID_IDS and zc.tiles[r][c] != 0:
                    # Don't spawn on portal tiles
                    if (r, c) not in zc.portals:
                        walkable.append((r, c))

        if not walkable:
            return

        names = ["Ash", "Beck", "Crow", "Dex", "Eve", "Finn", "Grim",
                 "Hale", "Iris", "Jax", "Kit", "Lux", "Moss", "Nix"]

        npc_colors = [
            (100, 180, 255), (255, 140, 100), (140, 255, 170),
            (255, 200, 100), (200, 140, 255), (255, 120, 180),
        ]

        for _ in range(count):
            r, c = random.choice(walkable)
            self._next_npc_id += 1
            nid = self._next_npc_id
            name = names[nid % len(names)]
            color = npc_colors[nid % len(npc_colors)]

            eid = self.world.spawn()
            self.world.add(eid, CoarsePos(
                row=r, col=c, zone=zone_name,
                speed=1.5 + random.random() * 1.5,
            ))
            self.world.add(eid, Identity(
                name=f"{name}#{nid}", kind=EntityKind.NPC,
            ))
            self.world.add(eid, Health(current=100, maximum=100))
            self.world.add(eid, Timers(active={}))
            self.world.add(eid, Sprite(
                char="N", color=color, layer=5,
            ))
            self.world.add(eid, Collider(w=0.6, h=0.6, solid=True))
            self.world.add(eid, Facing())

            self._log(f"Spawned {name}#{nid} in {zone_name} ({r},{c})")

    # ── Portal transition logic ───────────────────────────────────

    def _check_player_portal(self) -> None:
        """Check if the player is on a portal tile and start a transition."""
        if self._fade_dir != 0:
            return  # already in a transition

        result = self.world.query_one(Player, Position)
        if not result:
            return
        _, _, pos = result
        pr = int(pos.y + 0.4)
        pc = int(pos.x + 0.4)
        key = (pr, pc)

        # Clear arrival suppression once player moves off the tile
        if self._portal_arrival is not None and key != self._portal_arrival:
            self._portal_arrival = None

        if key == self._portal_arrival:
            return

        zc = self.zone_sim.get_zone(self.active_zone)
        if zc is None or key not in zc.portals:
            return

        target_zone, target_r, target_c = zc.portals[key]
        if not self.zone_sim.has_zone(target_zone):
            return

        # Start fade-out
        self._pending_tp = (target_zone, target_r, target_c)
        self._fade_dir = 1
        self._log(f"Portal -> {target_zone} ({target_r},{target_c})")

    def _execute_transition(self) -> None:
        """Perform the actual zone switch (called when fade-out completes)."""
        if self._pending_tp is None:
            return

        target_zone, target_r, target_c = self._pending_tp
        self._pending_tp = None
        old_zone = self.active_zone
        self.active_zone = target_zone

        # Move player
        result = self.world.query_one(Player, Position)
        if result:
            _, _, pos = result
            pos.x = float(target_c) + 0.5
            pos.y = float(target_r) + 0.5
            pos.zone = target_zone

        # Update player CoarsePos too
        presult = self.world.query_one(Player, CoarsePos)
        if presult:
            _, _, cp = presult
            cp.row = target_r
            cp.col = target_c
            cp.zone = target_zone

        # Suppress re-trigger at destination
        self._portal_arrival = (target_r, target_c)

        # Sync LOD: promote new zone's NPCs, demote old zone's NPCs
        sync_zone_lod(self.world, self.active_zone)

        # Update tile cache
        self._cache_active_zone()

        # Count transitions for log
        n_promoted = sum(1 for eid, cp in self.world.all_of(CoarsePos)
                         if cp.zone == target_zone
                         and self.world.has(eid, Position)
                         and not self.world.has(eid, Player))
        n_demoted = sum(1 for eid, cp in self.world.all_of(CoarsePos)
                        if cp.zone == old_zone
                        and not self.world.has(eid, Position))

        self._log(f"Entered {target_zone} (promoted={n_promoted}, "
                  f"demoted={n_demoted})")
        self._flash(f"-> {target_zone}", COL_ACCENT)

    # ── Event handling ────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App) -> None:
        if event.type != pygame.KEYDOWN:
            return

        key = event.key

        if key == pygame.K_ESCAPE:
            app.pop_scene()
            return

        # Number keys select viewed zone
        if pygame.K_1 <= key <= pygame.K_9:
            idx = key - pygame.K_1
            if idx < len(self.available_zones):
                self.viewed_zone = self.available_zones[idx]
                self._log(f"Viewing: {self.viewed_zone}")

        elif key == pygame.K_SPACE:
            self._spawn_test_npcs(self.viewed_zone, count=1)

        elif key == pygame.K_p:
            self.paused = not self.paused
            self._log(f"Sim {'PAUSED' if self.paused else 'RUNNING'}")

        elif key in (pygame.K_EQUALS, pygame.K_PLUS):
            self.zone_sim.tick_interval = max(0.1,
                                              self.zone_sim.tick_interval - 0.1)
            self._log(f"Tick interval: {self.zone_sim.tick_interval:.1f}s")

        elif key == pygame.K_MINUS:
            self.zone_sim.tick_interval = min(5.0,
                                              self.zone_sim.tick_interval + 0.1)
            self._log(f"Tick interval: {self.zone_sim.tick_interval:.1f}s")

        elif key == pygame.K_v:
            self._show_vision = not self._show_vision
            self._log(f"Vision overlay {'ON' if self._show_vision else 'OFF'}")

    # ── Update ────────────────────────────────────────────────────

    def update(self, dt: float, app: App) -> None:
        # ── Fade transition ──
        if self._fade_dir != 0:
            self._fade_alpha += self._fade_dir * self._fade_speed * dt
            if self._fade_dir == 1 and self._fade_alpha >= 1.0:
                self._fade_alpha = 1.0
                self._execute_transition()
                self._fade_dir = -1   # start fade-in
            elif self._fade_dir == -1 and self._fade_alpha <= 0.0:
                self._fade_alpha = 0.0
                self._fade_dir = 0

        # ── Player input (WASD) — suppress during fade ──
        dx = dy = 0.0
        if self._fade_dir == 0:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                dx += 1
            if dx and dy:
                dx *= 0.7071
                dy *= 0.7071

        for eid, player, vel in self.world.query(Player, Velocity):
            vel.x = dx * player.speed
            vel.y = dy * player.speed
            facing = self.world.get(eid, Facing)
            if facing and (abs(vel.x) > 0.01 or abs(vel.y) > 0.01):
                if abs(vel.x) >= abs(vel.y):
                    facing.direction = (Direction.RIGHT if vel.x > 0
                                        else Direction.LEFT)
                else:
                    facing.direction = (Direction.DOWN if vel.y > 0
                                        else Direction.UP)

        # ── Physics for the active zone ──
        if self._active_tiles:
            movement_system(self.world, dt, self._active_tiles,
                            portal_tiles=self._portal_positions)

        # ── Check portal overlap (only when not fading) ──
        if self._fade_dir == 0:
            self._check_player_portal()

        # ── Camera follow player ──
        cam = self.world.resources.try_get(Camera)
        result = self.world.query_one(Player, Position)
        if cam and result:
            _, _, pos = result
            cam.x = pos.x
            cam.y = pos.y

        # ── Tick timers on ALL entities ──
        tick_timers(self.world, dt)

        # ── Off-screen sim ──
        if not self.paused:
            ticks = self.zone_sim.tick(dt, self.active_zone)
            self.total_ticks += ticks

        # ── Flash timer ──
        if self._flash_timer > 0:
            self._flash_timer -= dt

        # ── Game clock ──
        clock = self.world.resources.try_get(GameClock)
        if clock:
            clock.time += dt

        self.world.purge()

    # ══════════════════════════════════════════════════════════════
    #  Draw
    # ══════════════════════════════════════════════════════════════

    def draw(self, surface: pygame.Surface, app: App) -> None:
        surface.fill(COL_BG)
        sw, sh = surface.get_size()

        panel_h = sh - STATUS_H - LOG_H

        # ── Left panel: active zone at real resolution ──
        self._draw_active_panel(surface, app, 0, 0, LEFT_W, panel_h)

        # ── Divider ──
        pygame.draw.line(surface, COL_DIVIDER,
                         (LEFT_W, 0), (LEFT_W, panel_h), 2)

        # ── Right panel: coarse zone minimap ──
        self._draw_coarse_panel(surface, app, LEFT_W, 0, RIGHT_W, panel_h)

        # ── Status bar ──
        self._draw_status(surface, app, 0, panel_h, sw, STATUS_H)

        # ── Log ──
        self._draw_log(surface, app, 0, panel_h + STATUS_H, sw, LOG_H)

        # ── Flash overlay ──
        if self._flash_timer > 0:
            alpha = min(255, int(self._flash_timer * 300))
            txt = app.font_lg.render(self._flash_text, True, self._flash_color)
            txt.set_alpha(alpha)
            surface.blit(txt, (sw // 2 - txt.get_width() // 2,
                               panel_h // 2 - 10))

        # ── Fade overlay (portal transition) ──
        if self._fade_alpha > 0.01:
            fade_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
            a = int(self._fade_alpha * 255)
            fade_surf.fill((0, 0, 0, a))
            surface.blit(fade_surf, (0, 0))

    # ── Active zone panel (real resolution) ───────────────────────

    def _draw_active_panel(self, surface: pygame.Surface, app: App,
                           px: int, py: int, pw: int, ph: int) -> None:
        """Render the active zone exactly like the TopDown scene."""
        clip_rect = pygame.Rect(px, py, pw, ph)
        surface.set_clip(clip_rect)
        pygame.draw.rect(surface, (20, 20, 25), clip_rect)

        zc = self.zone_sim.get_zone(self.active_zone)
        if zc is None:
            app.draw_text(surface, f"No zone: {self.active_zone}",
                          px + 8, py + 20, COL_TEXT, app.font)
            surface.set_clip(None)
            return

        cam = self.world.resources.try_get(Camera) or Camera()

        # Camera offset: centre of panel maps to camera position
        cx = px + pw // 2 - int(cam.x * TILE_SIZE)
        cy = py + ph // 2 - int(cam.y * TILE_SIZE)

        # Visible tile range (culling)
        c0 = max(0, (px - cx) // TILE_SIZE)
        r0 = max(0, (py - cy) // TILE_SIZE)
        c1 = min(zc.width, (px + pw - cx) // TILE_SIZE + 1)
        r1 = min(zc.height, (py + ph - cy) // TILE_SIZE + 1)

        # ── Tiles at real TILE_SIZE ──
        for row in range(r0, r1):
            for col in range(c0, c1):
                tid = zc.tiles[row][col]
                color = TILE_COLORS.get(tid, (40, 40, 40))
                rect = (cx + col * TILE_SIZE, cy + row * TILE_SIZE,
                        TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, color, rect)

        # ── Portal highlights ──
        for (pr, pc), (tz, _, _) in zc.portals.items():
            rect = pygame.Rect(cx + pc * TILE_SIZE, cy + pr * TILE_SIZE,
                               TILE_SIZE, TILE_SIZE)
            pygame.draw.rect(surface, COL_PORTAL, rect, 2)
            # Tiny label
            lbl = app.font_sm.render(tz[:6], True, COL_PORTAL)
            surface.blit(lbl, (rect.centerx - lbl.get_width() // 2,
                               rect.top - lbl.get_height() - 1))

        # ── Entities (sprites, health bars) ──
        for eid, pos, sprite in self.world.query(Position, Sprite):
            if pos.zone != self.active_zone:
                continue

            ex = cx + int(pos.x * TILE_SIZE)
            ey = cy + int(pos.y * TILE_SIZE)

            # Tile entity indicators
            te = self.world.get(eid, TileEntity)
            if te:
                if te.tile_type == "container":
                    pygame.draw.rect(surface, (180, 140, 80),
                                     (ex - TILE_SIZE // 2,
                                      ey - TILE_SIZE // 2,
                                      TILE_SIZE, TILE_SIZE), 1)
                elif te.tile_type == "ground_item":
                    pygame.draw.circle(surface, (220, 220, 120),
                                       (ex, ey), TILE_SIZE // 3, 1)

            # Sprite glyph
            img = app.font.render(sprite.char, True, sprite.color)
            surface.blit(img, (ex - img.get_width() // 2,
                               ey - img.get_height() // 2))

            # Health bar (non-player, damaged)
            hp = self.world.get(eid, Health)
            is_player = self.world.has(eid, Player)
            if hp and not is_player and hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                ratio = max(0.0, hp.current / hp.maximum) if hp.maximum > 0 else 0.0
                bar_x = ex - bar_w // 2
                bar_y = ey - img.get_height() // 2 - 6
                pygame.draw.rect(surface, (60, 0, 0),
                                 (bar_x, bar_y, bar_w, 3))
                pygame.draw.rect(surface, (0, 200, 0),
                                 (bar_x, bar_y, int(bar_w * ratio), 3))

            # Name label for NPCs
            if not is_player:
                ident = self.world.get(eid, Identity)
                if ident:
                    lbl = app.font_sm.render(ident.name[:10], True,
                                             (160, 160, 160))
                    surface.blit(lbl, (ex - lbl.get_width() // 2,
                                       ey + img.get_height() // 2 + 1))

        # ── LOD badges on promoted NPCs ──
        for eid, pos in self.world.all_of(Position):
            if pos.zone != self.active_zone:
                continue
            if self.world.has(eid, Player):
                continue
            if self.world.has(eid, CoarsePos):
                ex = cx + int(pos.x * TILE_SIZE)
                ey = cy + int(pos.y * TILE_SIZE)
                # Small green "F" badge = fine/promoted
                lbl = app.font_sm.render("F", True, COL_PROMOTE)
                surface.blit(lbl, (ex + 6, ey - 10))

        # ── Panel header overlay ──
        header = pygame.Surface((pw, 16), pygame.SRCALPHA)
        header.fill((0, 0, 0, 140))
        surface.blit(header, (px, py))
        app.draw_text(surface, f"ACTIVE: {self.active_zone}",
                      px + 6, py + 1, COL_PROMOTE, app.font_sm)

        # Player position readout
        result = self.world.query_one(Player, Position)
        if result:
            _, _, ppos = result
            pos_text = f"({ppos.x:.1f}, {ppos.y:.1f})"
            app.draw_text(surface, pos_text,
                          px + pw - 100, py + 1, COL_DIM, app.font_sm)

        surface.set_clip(None)

    # ── Coarse zone panel (minimap style) ─────────────────────────

    def _draw_coarse_panel(self, surface: pygame.Surface, app: App,
                           px: int, py: int, pw: int, ph: int) -> None:
        """Render the selected zone as a coarse tile grid with markers."""
        clip_rect = pygame.Rect(px, py, pw, ph)
        surface.set_clip(clip_rect)
        pygame.draw.rect(surface, COL_COARSE_BG, clip_rect)

        zc = self.zone_sim.get_zone(self.viewed_zone)
        if zc is None:
            app.draw_text(surface, f"No zone: {self.viewed_zone}",
                          px + 8, py + 20, COL_TEXT, app.font)
            surface.set_clip(None)
            return

        # Scale tiles to fit the panel
        margin_top = 20
        margin_side = 8
        margin_bot = 16
        avail_w = pw - margin_side * 2
        avail_h = ph - margin_top - margin_bot

        tile_w = max(4, avail_w // max(1, zc.width))
        tile_h = max(4, avail_h // max(1, zc.height))
        ts = min(tile_w, tile_h)

        off_x = px + margin_side + (avail_w - ts * zc.width) // 2
        off_y = py + margin_top + (avail_h - ts * zc.height) // 2

        # ── Panel header ──
        header = pygame.Surface((pw, 16), pygame.SRCALPHA)
        header.fill((0, 0, 0, 140))
        surface.blit(header, (px, py))

        # Zone selector indicators
        sel_parts: list[str] = []
        for i, zn in enumerate(self.available_zones):
            marker = "*" if zn == self.active_zone else ""
            if zn == self.viewed_zone:
                sel_parts.append(f"[{i+1}]{marker}")
            else:
                sel_parts.append(f" {i+1} {marker}")
        sel_text = " ".join(sel_parts)
        is_active = self.viewed_zone == self.active_zone
        header_label = "ACTIVE" if is_active else "COARSE"
        header_col = COL_PROMOTE if is_active else COL_ACCENT
        app.draw_text(surface,
                      f"{header_label}: {self.viewed_zone}  {sel_text}",
                      px + 6, py + 1, header_col, app.font_sm)

        # ── Tiles ──
        for r in range(zc.height):
            for c in range(zc.width):
                tid = zc.tiles[r][c]
                base = TILE_COLORS.get(tid, (30, 30, 30))
                color = (max(0, base[0] - 15),
                         max(0, base[1] - 15),
                         max(0, base[2] - 15))
                rect = pygame.Rect(off_x + c * ts, off_y + r * ts, ts, ts)
                pygame.draw.rect(surface, color, rect)
                if ts >= 8:
                    pygame.draw.rect(surface, COL_GRID, rect, 1)

        # ── NPC vision overlay ──
        if self._show_vision:
            positions = self.zone_sim.zone_entity_positions(self.viewed_zone)
            vis_surf = pygame.Surface((ts * zc.width, ts * zc.height),
                                      pygame.SRCALPHA)
            for eid_v, _, _, _ in positions:
                if self.world.has(eid_v, Player):
                    continue
                vis = self.zone_sim.entity_vision(eid_v)
                for vr, vc in vis:
                    rect = pygame.Rect(vc * ts, vr * ts, ts, ts)
                    pygame.draw.rect(vis_surf, (50, 50, 140, 50), rect)
            surface.blit(vis_surf, (off_x, off_y))

        # ── NPC A* paths ──
        positions = self.zone_sim.zone_entity_positions(self.viewed_zone)
        for eid_p, row, col, name in positions:
            if self.world.has(eid_p, Player):
                continue
            path = self.zone_sim.entity_path(eid_p)
            if path and ts >= 6:
                for pr_p, pc_p in path:
                    rect = pygame.Rect(off_x + pc_p * ts + ts // 4,
                                       off_y + pr_p * ts + ts // 4,
                                       ts // 2, ts // 2)
                    pygame.draw.rect(surface, (60, 200, 100), rect)

        # ── Portal tiles ──
        for (pr, pc), (tz, _, _) in zc.portals.items():
            rect = pygame.Rect(off_x + pc * ts, off_y + pr * ts, ts, ts)
            pygame.draw.rect(surface, COL_PORTAL, rect, 2)
            if ts >= 12:
                lbl = app.font_sm.render(tz[:6], True, COL_PORTAL)
                surface.blit(lbl, (rect.x, rect.bottom + 1))

        # ── Coarse entities (square markers) ──
        for eid_e, row, col, name in positions:
            ecx = off_x + col * ts + ts // 2
            ecy = off_y + row * ts + ts // 2

            is_player = self.world.has(eid_e, Player)
            sprite = self.world.get(eid_e, Sprite)
            color = (COL_PLAYER if is_player
                     else (sprite.color if sprite else COL_COARSE_NPC))

            half = max(3, ts // 3)
            marker = pygame.Rect(ecx - half, ecy - half, half * 2, half * 2)
            pygame.draw.rect(surface, color, marker)
            pygame.draw.rect(surface, (255, 255, 255), marker, 1)

            # C/F badge showing LOD state
            has_fine = self.world.has(eid_e, Position)
            badge = "F" if has_fine else "C"
            badge_col = COL_PROMOTE if has_fine else COL_DEMOTE
            if ts >= 10:
                lbl = app.font_sm.render(f"{name[:6]} {badge}", True,
                                         badge_col)
                surface.blit(lbl, (ecx + half + 3, ecy - 5))

        # ── Fine-position entities visiting this zone (circle) ──
        for eid_f, pos_f, sprite_f in self.world.query(Position, Sprite):
            if pos_f.zone != self.viewed_zone:
                continue
            # Don't double-draw entities already shown from CoarsePos
            if self.world.has(eid_f, CoarsePos):
                cp_f = self.world.get(eid_f, CoarsePos)
                if cp_f and cp_f.zone == self.viewed_zone:
                    continue
            ecx = off_x + int(pos_f.x * ts)
            ecy = off_y + int(pos_f.y * ts)
            radius = max(2, ts // 4)
            pygame.draw.circle(surface, COL_PROMOTE, (ecx, ecy), radius)
            pygame.draw.circle(surface, (255, 255, 255),
                               (ecx, ecy), radius, 1)

        # ── Entity count ──
        n_coarse = len(positions)
        n_fine = sum(1 for _, p, _ in self.world.query(Position, Sprite)
                     if p.zone == self.viewed_zone)
        count_text = f"Coarse: {n_coarse}  Fine: {n_fine}"
        app.draw_text(surface, count_text,
                      px + 6, py + ph - 14, COL_DIM, app.font_sm)

        surface.set_clip(None)

    # ── Status bar ────────────────────────────────────────────────

    def _draw_status(self, surface: pygame.Surface, app: App,
                     x: int, y: int, w: int, h: int) -> None:
        pygame.draw.rect(surface, (25, 25, 32), (x, y, w, h))
        pygame.draw.line(surface, COL_DIVIDER, (x, y), (x + w, y), 1)

        n_fine = sum(1 for _ in self.world.all_of(Position))
        n_coarse_only = sum(
            1 for eid, _ in self.world.all_of(CoarsePos)
            if not self.world.has(eid, Position)
        )
        paused_tag = "  PAUSED" if self.paused else ""

        line1 = (f"Entities: {n_fine + n_coarse_only} "
                 f"(fine={n_fine} coarse={n_coarse_only})  |  "
                 f"Ticks: {self.total_ticks}  |  "
                 f"Rate: {self.zone_sim.tick_interval:.1f}s{paused_tag}")
        app.draw_text(surface, line1, x + 8, y + 4, COL_TEXT, app.font_sm)

        # Per-zone breakdown
        zone_parts: list[str] = []
        for zn in self.available_zones:
            nc = sum(1 for eid, cp in self.world.all_of(CoarsePos)
                     if cp.zone == zn
                     and not self.world.has(eid, Position))
            nf = sum(1 for _, p in self.world.all_of(Position)
                     if p.zone == zn)
            tag = ">" if zn == self.active_zone else " "
            zone_parts.append(f"{tag}{zn}: {nf}f/{nc}c")
        line2 = "  ".join(zone_parts)
        app.draw_text(surface, line2, x + 8, y + 18, COL_DIM, app.font_sm)

        controls = ("WASD=move  1-9=view  Space=spawn  "
                    "V=vision  P=pause  +/-=rate  Esc=exit")
        app.draw_text(surface, controls,
                      x + 8, y + 34, (70, 80, 75), app.font_sm)

    # ── Event log ─────────────────────────────────────────────────

    def _draw_log(self, surface: pygame.Surface, app: App,
                  x: int, y: int, w: int, h: int) -> None:
        pygame.draw.rect(surface, (15, 15, 18), (x, y, w, h))
        pygame.draw.line(surface, COL_DIVIDER, (x, y), (x + w, y), 1)

        max_lines = (h - 4) // 13
        visible = self.log[-max_lines:]
        for i, line in enumerate(visible):
            age = len(visible) - 1 - i
            alpha_f = max(0.35, 1.0 - age * 0.12)
            c = int(150 * alpha_f)
            app.draw_text(surface, line, x + 8, y + 3 + i * 13,
                          (c, c, c), app.font_sm)

    # ── Helpers ───────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 100:
            self.log = self.log[-80:]

    def _flash(self, msg: str, color: tuple[int, int, int]) -> None:
        self._flash_timer = 1.2
        self._flash_text = msg
        self._flash_color = color


# ── Standalone runner ─────────────────────────────────────────────────

def run_exhibit() -> None:
    """Launch the LOD exhibit as a standalone window."""
    app = App(title="LOD Exhibit", width=960, height=640)
    app.push_scene(ExhibitLOD())
    app.run()


if __name__ == "__main__":
    run_exhibit()
