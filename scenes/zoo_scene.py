"""scenes/zoo_scene.py — Entity Zoo / Bestiary.

Auto-scans characters.toml and items.toml.  Spawns each entry in a
labeled grid cell so you can inspect every entity's stats at a glance.

Controls:
    Arrow keys / WASD  — pan camera (hold Shift for 3× speed)
    LMB / Enter        — select entity for sidebar detail
    Tab                — toggle items vs characters
    /                  — search / filter entries
    F                  — toggle animate (unfreeze brains)
    G                  — toggle grid overlay
    F1                 — debug overlay
    F3                 — scene picker
    F4                 — reload tuning
    Escape             — back
"""

from __future__ import annotations
from pathlib import Path
import math
import pygame
from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS, TILE_GRASS, TILE_WALL, TILE_STONE
from core.zone import ZONE_MAPS
from components import (
    Position, Velocity, Sprite, Identity, Camera, Collider,
    Health, Hunger, Brain, Facing, Lod, GameClock,
    Hurtbox, Equipment, Inventory, Needs,
)
from components.ai import HomeRange, Threat, AttackConfig, VisionCone
from components.social import Faction, Dialogue
from components.combat import CombatStats, Loot, LootTableRef
from logic.entity_factory import spawn_from_descriptor
from scenes.test_scene_base import TestScene

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore


# ── Grid layout constants ───────────────────────────────────────────

CELL_W = 6   # tiles per cell horizontal
CELL_H = 6   # tiles per cell vertical
COLS   = 6   # cells per row


class ZooScene(TestScene):
    """Entity Zoo — auto-populated bestiary."""

    def __init__(self):
        super().__init__()
        self.zone = "__zoo__"
        self.mode = "characters"  # "characters" | "items"
        self._char_data: dict = {}
        self._item_data: dict = {}
        self._entries: list[tuple[str, dict]] = []  # (id, descriptor)
        self._cell_map: dict[int, tuple[int, int, str]] = {}  # eid → (gx, gy, label)

        # Selection
        self._selected_eid: int | None = None

        # Search / filter
        self._filter: str = ""
        self._filtering: bool = False

        # Animate toggle
        self._animate: bool = False
        self.show_grid: bool = False

        self._load_data()

    def _load_data(self):
        root = Path(__file__).resolve().parent.parent / "data"
        if tomllib is None:
            return
        char_path = root / "characters.toml"
        item_path = root / "items.toml"
        if char_path.exists():
            with open(char_path, "rb") as f:
                self._char_data = tomllib.load(f)
        if item_path.exists():
            with open(item_path, "rb") as f:
                self._item_data = tomllib.load(f)

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_enter(self, app: App):
        super().on_enter(app)  # Camera, Clock, Tuning, DevLog
        self._populate(app)

    def on_exit(self, app: App):
        self._cell_map.clear()
        super().on_exit(app)  # kills all _eids, purges

    def _populate(self, app: App):
        """Spawn all entries in a grid layout."""
        # Clean previous
        for eid in self._eids:
            if app.world.alive(eid):
                app.world.kill(eid)
        app.world.purge()
        self._eids.clear()
        self._cell_map.clear()

        data = self._char_data if self.mode == "characters" else self._item_data
        # Apply filter
        if self._filter:
            filt = self._filter.lower()
            all_entries = [(k, v) for k, v in data.items()
                           if filt in k.lower()
                           or filt in str(v.get("identity", {}).get("name", "")).lower()
                           or filt in str(v.get("brain", {}).get("kind", "")).lower()
                           or filt in str(v.get("faction", {}).get("group", "")).lower()]
        else:
            all_entries = list(data.items())

        self._entries = all_entries
        n = len(self._entries)
        rows = max(1, math.ceil(n / COLS))

        # Build tile grid
        self.map_w = COLS * CELL_W + 2
        self.map_h = rows * CELL_H + 2
        self.tiles = [[TILE_GRASS] * self.map_w for _ in range(self.map_h)]
        # Border
        for r in range(self.map_h):
            self.tiles[r][0] = TILE_WALL
            self.tiles[r][self.map_w - 1] = TILE_WALL
        for c in range(self.map_w):
            self.tiles[0][c] = TILE_WALL
            self.tiles[self.map_h - 1][c] = TILE_WALL
        # Cell dividers (stone floor)
        for i in range(COLS + 1):
            c = 1 + i * CELL_W
            if c < self.map_w:
                for r in range(self.map_h):
                    if self.tiles[r][c] != TILE_WALL:
                        self.tiles[r][c] = TILE_STONE
        for j in range(rows + 1):
            r = 1 + j * CELL_H
            if r < self.map_h:
                for c in range(self.map_w):
                    if self.tiles[r][c] != TILE_WALL:
                        self.tiles[r][c] = TILE_STONE

        ZONE_MAPS[self.zone] = self.tiles

        cam = self._camera
        if cam:
            cam.x = self.map_w / 2.0
            cam.y = self.map_h / 2.0

        # Spawn entities into cells
        for idx, (entry_id, entry_data) in enumerate(self._entries):
            row_idx = idx // COLS
            col_idx = idx % COLS
            cx = 1 + col_idx * CELL_W + CELL_W // 2
            cy = 1 + row_idx * CELL_H + CELL_H // 2

            if self.mode == "characters":
                desc = dict(entry_data)
                # Override position to place in cell
                desc["position"] = {"x": float(cx), "y": float(cy)}
                # Strip subzone_pos so they get real positions
                desc.pop("subzone_pos", None)
                try:
                    eid = spawn_from_descriptor(app.world, desc, self.zone)
                    # Force high-LOD and active brain
                    lod = app.world.get(eid, Lod)
                    if lod:
                        lod.level = "high"
                    brain = app.world.get(eid, Brain)
                    if brain:
                        brain.active = self._animate
                except Exception as ex:
                    print(f"[ZOO] Failed to spawn {entry_id}: {ex}")
                    continue
            else:
                # Item: spawn as a display entity
                eid = app.world.spawn()
                ident_data = entry_data.get("identity", {})
                sprite_data = entry_data.get("sprite", {})
                app.world.add(eid, Position(x=float(cx), y=float(cy), zone=self.zone))
                app.world.add(eid, Identity(
                    name=ident_data.get("name", entry_id),
                    kind="item",
                ))
                app.world.add(eid, Sprite(
                    char=sprite_data.get("char", "?"),
                    color=tuple(sprite_data.get("color", [200, 200, 200])),
                ))
                app.world.zone_add(eid, self.zone)

            label = entry_id
            if self.mode == "characters":
                ident = app.world.get(eid, Identity)
                if ident:
                    label = ident.name
            else:
                label = entry_data.get("identity", {}).get("name", entry_id)

            self._eids.append(eid)
            self._cell_map[eid] = (cx, cy, label)

    # ── Events ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        # Search mode intercepts all typing
        if self._filtering:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN or event.key == pygame.K_ESCAPE:
                    self._filtering = False
                    if event.key == pygame.K_ESCAPE:
                        self._filter = ""
                    self._populate(app)
                elif event.key == pygame.K_BACKSPACE:
                    self._filter = self._filter[:-1]
                else:
                    ch = event.unicode
                    if ch and ch.isprintable():
                        self._filter += ch
            return

        # Shared keys: F1, F3, F4, Escape
        super().handle_event(event, app)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self.mode = "items" if self.mode == "characters" else "characters"
                self._filter = ""
                self._populate(app)
            elif event.key == pygame.K_SLASH:
                self._filtering = True
            elif event.key == pygame.K_f:
                self._animate = not self._animate
                # Toggle all brains
                for eid in self._eids:
                    brain = app.world.get(eid, Brain)
                    if brain:
                        brain.active = self._animate
            elif event.key == pygame.K_g:
                self.show_grid = not self.show_grid
            elif event.key == pygame.K_RETURN and self._selected_eid is not None:
                pass  # Could expand to a detail view
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._try_select(app)

    def _try_select(self, app: App):
        rc = self._mouse_to_tile(app)
        if not rc:
            self._selected_eid = None
            return
        row, col = rc
        world_x = col + 0.5
        world_y = row + 0.5

        best_eid = None
        best_dist = 3.0  # max click distance in tiles
        for eid in self._eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            if not pos:
                continue
            d = math.hypot(pos.x - world_x, pos.y - world_y)
            if d < best_dist:
                best_dist = d
                best_eid = eid
        self._selected_eid = best_eid

    # ── Update ───────────────────────────────────────────────────────

    def update(self, dt: float, app: App):
        # Camera pan
        keys = pygame.key.get_pressed()
        pan_speed = 36.0 if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) else 12.0
        cam = self._camera
        if cam:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                cam.x -= pan_speed * dt
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                cam.x += pan_speed * dt
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                cam.y -= pan_speed * dt
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                cam.y += pan_speed * dt

        # Animate NPCs if toggled on
        if self._animate:
            from logic.tick import tick_systems
            tick_systems(app.world, dt, self.tiles,
                         skip_lod=True, skip_needs=True)
            app.world.purge()

    # ── Draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill((16, 20, 24))
        sw, sh = surface.get_size()
        ox, oy = self._cam_offset(surface)

        # Tiles (shared renderer)
        self._draw_tiles(surface, show_grid=self.show_grid)

        # Entities with labels
        for eid in self._eids:
            if not app.world.alive(eid):
                continue
            pos = app.world.get(eid, Position)
            sprite = app.world.get(eid, Sprite)
            if not pos or not sprite:
                continue
            sx = ox + int(pos.x * TILE_SIZE)
            sy = oy + int(pos.y * TILE_SIZE)

            # Selection highlight
            if eid == self._selected_eid:
                sel_rect = pygame.Rect(sx - 2, sy - 2, TILE_SIZE + 4, TILE_SIZE + 4)
                pygame.draw.rect(surface, (0, 255, 200), sel_rect, 2)

            app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                          color=sprite.color, font=app.font_lg)

            # Cell label
            cell_info = self._cell_map.get(eid)
            if cell_info:
                _, _, label = cell_info
                app.draw_text(surface, label, sx - 12, sy - 18,
                              color=(200, 200, 200), font=app.font_sm)

                # Stat line under name
                stat_parts = []
                hp = app.world.get(eid, Health)
                if hp:
                    stat_parts.append(f"HP:{hp.maximum:.0f}")
                combat = app.world.get(eid, CombatStats)
                if combat:
                    stat_parts.append(f"DMG:{combat.damage:.0f}")
                    if combat.defense > 0:
                        stat_parts.append(f"DEF:{combat.defense:.0f}")
                faction = app.world.get(eid, Faction)
                if faction:
                    stat_parts.append(f"{faction.group}/{faction.disposition}")
                brain = app.world.get(eid, Brain)
                if brain:
                    stat_parts.append(f"brain:{brain.kind}")

                # For items, show item-specific stats
                if self.mode == "items":
                    entry_idx = self._eids.index(eid) if eid in self._eids else -1
                    if 0 <= entry_idx < len(self._entries):
                        _, edata = self._entries[entry_idx]
                        itype = edata.get("type", "?")
                        stat_parts = [f"type:{itype}"]
                        if "damage" in edata:
                            stat_parts.append(f"DMG:{edata['damage']}")
                        if "heal" in edata:
                            stat_parts.append(f"HEAL:{edata['heal']}")
                        if "style" in edata:
                            stat_parts.append(edata["style"])
                        if "range" in edata:
                            stat_parts.append(f"RNG:{edata['range']}")

                if stat_parts:
                    stat_str = "  ".join(stat_parts)
                    app.draw_text(surface, stat_str, sx - 12, sy - 8,
                                  color=(140, 160, 140), font=app.font_sm)

        # ── Header bar ───────────────────────────────────────────────
        bar = pygame.Surface((sw, 28), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 180))
        surface.blit(bar, (0, 0))

        mode_label = "CHARS" if self.mode == "characters" else "ITEMS"
        count = len(self._entries)
        total = len(self._char_data if self.mode == "characters" else self._item_data)
        anim_tag = " [ANIMATE]" if self._animate else ""

        hdr = f"ZOO: {mode_label} ({count}/{total}){anim_tag}"
        app.draw_text(surface, hdr, 8, 7, (0, 255, 200), app.font_sm)

        # Controls hint (right side)
        hint = "[Tab]mode  [/]search  [F]anim  [G]grid  [Esc]back"
        app.draw_text(surface, hint, sw - len(hint) * 7 - 8, 7,
                      (80, 100, 90), app.font_sm)

        # ── Search bar ───────────────────────────────────────────────
        if self._filtering:
            bar2 = pygame.Surface((sw, 22), pygame.SRCALPHA)
            bar2.fill((0, 40, 30, 200))
            surface.blit(bar2, (0, 28))
            cursor = "_" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            app.draw_text(surface, f"Search: {self._filter}{cursor}", 8, 31,
                          (0, 255, 200), app.font_sm)
        elif self._filter:
            app.draw_text_bg(surface, f"Filter: \"{self._filter}\"  [/] to edit",
                             8, 31, (180, 200, 160))

        # ── Footer ───────────────────────────────────────────────────
        footer_parts = ["WASD/Arrows=pan", "Shift=fast", "LMB=select"]
        if self._animate:
            footer_parts.append("F=freeze")
        app.draw_text_bg(surface, "  ".join(footer_parts),
                         8, sh - 18, (140, 140, 140))

        # ── Sidebar (selected entity) ────────────────────────────────
        if self._selected_eid is not None and app.world.alive(self._selected_eid):
            self._draw_sidebar(surface, app, self._selected_eid)

    def _draw_sidebar(self, surface: pygame.Surface, app: App, eid: int):
        sw, sh = surface.get_size()
        panel_w = 220
        px = sw - panel_w - 4
        py = 30

        bg = pygame.Surface((panel_w, sh - 40), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        surface.blit(bg, (px, py))

        y = py + 8
        ident = app.world.get(eid, Identity)
        name = ident.name if ident else f"eid {eid}"
        app.draw_text(surface, f"-- {name} --", px + 8, y, (0, 255, 200), app.font_sm)
        y += 16
        app.draw_text(surface, f"EID: {eid}", px + 8, y, (180, 180, 180), app.font_sm)
        y += 14

        # Dump all known components
        component_info = [
            (Health, lambda c: f"HP: {c.current:.0f}/{c.maximum:.0f}"),
            (CombatStats, lambda c: f"DMG: {c.damage:.0f}  DEF: {c.defense:.0f}"),
            (Hunger, lambda c: f"Hunger: {c.current:.0f}/{c.maximum:.0f}  rate:{c.rate}"),
            (Faction, lambda c: f"Faction: {c.group} ({c.disposition})"),
            (Brain, lambda c: f"Brain: {c.kind}  active:{c.active}"),
            (HomeRange, lambda c: f"HomeRange: r={c.radius:.0f} spd={c.speed:.1f}"),
            (Threat, lambda c: f"Threat: aggro={c.aggro_radius:.0f} leash={c.leash_radius:.0f}"),
            (AttackConfig, lambda c: f"Attack: {c.attack_type} rng={c.range:.1f} cd={c.cooldown:.2f}"),
            (VisionCone, lambda c: f"Vision: fov={c.fov_degrees:.0f}\u00b0 dist={c.view_distance:.0f}"),
            (Equipment, lambda c: f"Equip: {c.weapon or 'none'}"),
            (Dialogue, lambda c: f"Dialogue: {c.tree_id or c.greeting[:20] + '...' if c.greeting else 'none'}"),
            (Needs, lambda c: f"Needs: {c.priority} (urg {c.urgency:.1f})"),
        ]
        for comp_cls, fmt_fn in component_info:
            comp = app.world.get(eid, comp_cls)
            if comp:
                try:
                    text = fmt_fn(comp)
                except Exception:
                    text = f"{comp_cls.__name__}: ?"
                app.draw_text(surface, text, px + 8, y, (200, 200, 200), app.font_sm)
                y += 14

        # Inventory
        inv = app.world.get(eid, Inventory)
        if inv and inv.items:
            app.draw_text(surface, "Inventory:", px + 8, y, (200, 200, 150), app.font_sm)
            y += 14
            for item_id, qty in list(inv.items.items())[:8]:
                app.draw_text(surface, f"  {item_id} x{qty}", px + 8, y, (180, 180, 180), app.font_sm)
                y += 13
