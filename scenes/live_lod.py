"""scenes/live_lod.py — Live LOD viewer for the current session.

A read-only diagnostic overlay that visualises the LOD state of the
*currently loaded* game (the session's World).  Unlike the standalone
LOD Exhibit, this does **not** create its own world — it reads directly
from the active session.

Shows:
  - A minimap per visited zone with coarse/fine entity dots
  - LOD status badges (promoted / demoted) per entity
  - Entity counts per zone
  - Active zone highlighted

Controls:
    1-9     Select zone tab to highlight / inspect
    Escape  Return to previous screen
"""

from __future__ import annotations

import pygame

from core.scene import Scene
from core.constants import TILE_SIZE
from core.tiles import TILE_COLORS, SOLID_IDS
from core.zones import load_zone, list_zones
from components import (
    Position, CoarsePos, Sprite, Identity, Health, Player,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App
    from core.session import Session


# ── Colours ───────────────────────────────────────────────────────────
COL_BG          = (12, 12, 16)
COL_PANEL       = (20, 20, 28)
COL_GRID        = (30, 30, 40)
COL_TEXT        = (180, 180, 180)
COL_DIM         = (100, 100, 110)
COL_ACTIVE_ZONE = (80, 255, 120)
COL_OTHER_ZONE  = (100, 140, 180)
COL_PLAYER      = (255, 255, 100)
COL_PROMOTED    = (80, 220, 120)
COL_DEMOTED     = (100, 140, 220)
COL_HIGHLIGHT   = (255, 200, 80)


class LiveLOD(Scene):
    """Read-only LOD state viewer for the current game session."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.world = session.world
        self._selected: int = 0          # index into _zone_names
        self._zone_names: list[str] = []
        self._zone_tiles: dict[str, list[list[str]]] = {}

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, app: "App") -> None:
        # Collect all zones the session knows about
        visited = sorted(self.session.visited_zones)
        available = list_zones()
        # Show visited zones first, then any others that exist
        seen = set(visited)
        rest = [z for z in available if z not in seen]
        self._zone_names = visited + rest

        # Cache tile grids for minimap rendering
        self._zone_tiles.clear()
        for zn in self._zone_names:
            try:
                zd = load_zone(zn)
                self._zone_tiles[zn] = zd.tiles
            except Exception:
                self._zone_tiles[zn] = []

        # Default-select the active zone
        if self.session.zone_name in self._zone_names:
            self._selected = self._zone_names.index(self.session.zone_name)

    # ── Events ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self._selected = (self._selected - 1) % max(1, len(self._zone_names))
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._selected = (self._selected + 1) % max(1, len(self._zone_names))
            elif pygame.K_1 <= event.key <= pygame.K_9:
                idx = event.key - pygame.K_1
                if idx < len(self._zone_names):
                    self._selected = idx

    def update(self, dt: float, app: "App") -> None:
        pass

    # ── Draw ──────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        surface.fill(COL_BG)
        sw, sh = surface.get_size()

        if not self._zone_names:
            app.draw_text(surface, "No zones loaded", sw // 2 - 60, sh // 2, COL_TEXT)
            return

        # ── Title ─────────────────────────────────────────────────
        title = app.font_lg.render("LIVE LOD VIEWER", True, COL_HIGHLIGHT)
        surface.blit(title, ((sw - title.get_width()) // 2, 6))

        # ── Zone tabs (top bar) ───────────────────────────────────
        tab_y = 30
        tab_x = 10
        for i, zn in enumerate(self._zone_names):
            is_active = (zn == self.session.zone_name)
            is_selected = (i == self._selected)

            if is_selected:
                col = COL_HIGHLIGHT
            elif is_active:
                col = COL_ACTIVE_ZONE
            elif zn in self.session.visited_zones:
                col = COL_OTHER_ZONE
            else:
                col = COL_DIM

            label = f"[{i+1}] {zn}"
            if is_active:
                label += " *"
            img = app.font_sm.render(label, True, col)
            surface.blit(img, (tab_x, tab_y))
            tab_x += img.get_width() + 14

        # ── Selected zone detail panel ────────────────────────────
        sel_zone = self._zone_names[self._selected]
        panel_y = 52
        self._draw_zone_detail(surface, app, sel_zone, 10, panel_y, sw - 20, sh - panel_y - 30)

        # ── Hint bar ──────────────────────────────────────────────
        hint = app.font_sm.render("[1-9 / Left/Right] Switch zone   [Esc] Back", True, COL_DIM)
        surface.blit(hint, ((sw - hint.get_width()) // 2, sh - 20))

    def _draw_zone_detail(self, surface: pygame.Surface, app: "App",
                          zone_name: str, px: int, py: int,
                          pw: int, ph: int) -> None:
        """Draw the minimap + entity list for a single zone."""
        tiles = self._zone_tiles.get(zone_name, [])
        map_h = len(tiles)
        map_w = len(tiles[0]) if tiles else 0
        is_active = (zone_name == self.session.zone_name)

        # ── Minimap (left side) ───────────────────────────────────
        minimap_w = min(pw // 2 - 20, 400)
        minimap_h = ph - 40

        if map_w > 0 and map_h > 0:
            cell = min(minimap_w // map_w, minimap_h // map_h, 16)
            cell = max(cell, 3)
            mm_pw = map_w * cell
            mm_ph = map_h * cell
            mm_x = px + 4
            mm_y = py + 30

            # Background
            pygame.draw.rect(surface, COL_PANEL, (mm_x - 2, mm_y - 2, mm_pw + 4, mm_ph + 4))

            # Tiles
            for r in range(map_h):
                for c in range(map_w):
                    tid = tiles[r][c]
                    col = TILE_COLORS.get(tid, (40, 40, 40))
                    if tid in SOLID_IDS:
                        col = (col[0] // 2, col[1] // 2, col[2] // 2)
                    pygame.draw.rect(surface, col,
                                     (mm_x + c * cell, mm_y + r * cell, cell, cell))

            # Grid lines (only if cells are big enough)
            if cell >= 6:
                for r in range(map_h + 1):
                    pygame.draw.line(surface, COL_GRID,
                                     (mm_x, mm_y + r * cell),
                                     (mm_x + mm_pw, mm_y + r * cell))
                for c in range(map_w + 1):
                    pygame.draw.line(surface, COL_GRID,
                                     (mm_x + c * cell, mm_y),
                                     (mm_x + c * cell, mm_y + mm_ph))

            # Entities — fine-grained (Position)
            for eid, pos in self.world.all_of(Position):
                if pos.zone != zone_name:
                    continue
                is_player = self.world.has(eid, Player)
                col = COL_PLAYER if is_player else COL_PROMOTED
                ex = mm_x + int(pos.x * cell)
                ey = mm_y + int(pos.y * cell)
                r = max(2, cell // 2)
                pygame.draw.circle(surface, col, (ex, ey), r)

            # Entities — coarse-only (CoarsePos without Position)
            for eid, cp in self.world.all_of(CoarsePos):
                if cp.zone != zone_name:
                    continue
                if self.world.has(eid, Position):
                    continue  # already drawn as fine
                ex = mm_x + int((cp.col + 0.5) * cell)
                ey = mm_y + int((cp.row + 0.5) * cell)
                r = max(2, cell // 3)
                pygame.draw.rect(surface, COL_DEMOTED,
                                 (ex - r, ey - r, r * 2, r * 2))

            # Zone label
            zone_col = COL_ACTIVE_ZONE if is_active else COL_OTHER_ZONE
            lbl = f"{zone_name}  ({map_w}x{map_h})"
            if is_active:
                lbl += "  [ACTIVE]"
            app.draw_text(surface, lbl, mm_x, py + 10, zone_col, app.font)
        else:
            app.draw_text(surface, f"{zone_name}: no tile data", px + 4, py + 10, COL_DIM)
            mm_pw = 0

        # ── Entity list (right side) ──────────────────────────────
        list_x = px + max(mm_pw + 20, pw // 2)
        list_y = py + 10
        app.draw_text(surface, "Entities", list_x, list_y, COL_HIGHLIGHT, app.font)
        list_y += 20

        entries: list[tuple[int, str, str, str]] = []  # (eid, name, lod, hp)

        # Fine-grained
        for eid, pos in self.world.all_of(Position):
            if pos.zone != zone_name:
                continue
            name = self._entity_name(eid)
            hp_str = self._entity_hp(eid)
            is_player = self.world.has(eid, Player)
            lod_tag = "PLAYER" if is_player else "fine"
            entries.append((eid, name, lod_tag, hp_str))

        # Coarse-only
        for eid, cp in self.world.all_of(CoarsePos):
            if cp.zone != zone_name:
                continue
            if self.world.has(eid, Position):
                continue
            name = self._entity_name(eid)
            hp_str = self._entity_hp(eid)
            entries.append((eid, name, "coarse", hp_str))

        if not entries:
            app.draw_text(surface, "(none)", list_x, list_y, COL_DIM, app.font_sm)
        else:
            for eid, name, lod_tag, hp_str in entries[:20]:
                if lod_tag == "PLAYER":
                    tag_col = COL_PLAYER
                elif lod_tag == "fine":
                    tag_col = COL_PROMOTED
                else:
                    tag_col = COL_DEMOTED

                line = f"#{eid:>3}  {name:<16} [{lod_tag:>6}]  {hp_str}"
                app.draw_text(surface, line, list_x, list_y, tag_col, app.font_sm)
                list_y += 14

            if len(entries) > 20:
                app.draw_text(surface, f"  ... +{len(entries) - 20} more",
                              list_x, list_y, COL_DIM, app.font_sm)

        # ── Summary ───────────────────────────────────────────────
        summary_y = py + ph - 16
        n_fine = sum(1 for _, _, t, _ in entries if t in ("fine", "PLAYER"))
        n_coarse = sum(1 for _, _, t, _ in entries if t == "coarse")
        summary = f"Total: {len(entries)}  |  Fine: {n_fine}  |  Coarse: {n_coarse}"
        app.draw_text(surface, summary, px + 4, summary_y, COL_TEXT, app.font_sm)

    # ── Helpers ───────────────────────────────────────────────────

    def _entity_name(self, eid: int) -> str:
        ident = self.world.get(eid, Identity)
        return ident.name if ident else f"eid-{eid}"

    def _entity_hp(self, eid: int) -> str:
        hp = self.world.get(eid, Health)
        if hp is None:
            return ""
        return f"{int(hp.current)}/{int(hp.maximum)}"
