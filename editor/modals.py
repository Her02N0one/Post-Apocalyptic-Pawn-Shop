"""editor/modals.py — Overlay dialogs: zone picker, text input,
prefab picker, portal wizard, add-component dialog.
"""

from __future__ import annotations

from typing import Any, Callable

import pygame

from core.tiles import TILE_COLORS
from core.constants import TILE_SIZE
from editor.ui import (
    Theme, UIContext, Button, TextField, NumberField, Dropdown,
    draw_text, draw_text_centered,
)
from editor.state import EditorState, list_zones, ZONES_DIR
from editor.canvas import get_prefab_defaults

import json

# ── Direction helpers ────────────────────────────────────────────────

DIRECTIONS = ["up", "down", "left", "right"]
DIR_ARROWS = {"up": "\u25B2", "down": "\u25BC",
              "left": "\u25C0", "right": "\u25B6"}


# ═════════════════════════════════════════════════════════════════════
#  Modal Manager — only one modal active at a time
# ═════════════════════════════════════════════════════════════════════

class ModalManager:
    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self._active: _BaseModal | None = None

    @property
    def active(self) -> bool:
        return self._active is not None

    def open(self, modal: "_BaseModal"):
        self._active = modal

    def close(self):
        self._active = None
        self.ctx.release_focus()

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if self._active:
            self._active.draw(surface, font, font_sm, dt)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Returns True if event was consumed."""
        if self._active:
            return self._active.handle_event(event)
        return False


# ═════════════════════════════════════════════════════════════════════
#  Base modal
# ═════════════════════════════════════════════════════════════════════

class _BaseModal:
    def __init__(self, manager: ModalManager):
        self.manager = manager
        self.state = manager.state
        self.ctx = manager.ctx

    def draw(self, surface, font, font_sm, dt):
        # Darken background
        sw, sh = surface.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        return False

    def _centered_rect(self, surface, width, height) -> pygame.Rect:
        sw, sh = surface.get_size()
        return pygame.Rect((sw - width) // 2, (sh - height) // 2,
                           width, height)

    def _draw_panel(self, surface, rect, title="",
                    border_color=Theme.ACCENT):
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, border_color, rect, 2, border_radius=10)
        if title:
            font = pygame.font.SysFont("monospace", 14)
            draw_text(surface, title, rect.x + 16, rect.y + 12,
                      border_color, font)


# ═════════════════════════════════════════════════════════════════════
#  TextInputModal
# ═════════════════════════════════════════════════════════════════════

class TextInputModal(_BaseModal):
    def __init__(self, manager: ModalManager, label: str,
                 initial: str, callback: Callable[[str], None]):
        super().__init__(manager)
        self.label = label
        self.callback = callback
        self.field = TextField(
            pygame.Rect(0, 0, 380, 28), self.ctx, value=initial)
        self.ctx.take_focus(self.field.uid)

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 420, 100)
        self._draw_panel(surface, rect, "")

        draw_text(surface, self.label, rect.x + 16, rect.y + 14,
                  Theme.TEXT_DIM, font_sm)
        self.field.rect = pygame.Rect(rect.x + 16, rect.y + 38, 388, 28)
        self.field.draw(surface, font, dt)
        draw_text(surface, "Enter = confirm  |  Esc = cancel",
                  rect.x + 16, rect.y + 74, Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                val = self.field.value.strip()
                if val:
                    self.callback(val)
                self.manager.close()
                return True
            if event.key == pygame.K_ESCAPE:
                self.manager.close()
                return True
        self.field.handle_event(event)
        return True


# ═════════════════════════════════════════════════════════════════════
#  ZonePickerModal
# ═════════════════════════════════════════════════════════════════════

class ZonePickerModal(_BaseModal):
    def __init__(self, manager: ModalManager):
        super().__init__(manager)
        self.zones = list_zones()
        self.scroll = 0

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        sw, sh = surface.get_size()
        rect = self._centered_rect(surface, 500, sh - 120)
        self._draw_panel(surface, rect, "Select Zone")

        item_h = 32
        list_y = rect.y + 40
        clip = pygame.Rect(rect.x + 8, list_y, rect.w - 16, rect.h - 60)
        surface.set_clip(clip)
        mx, my = pygame.mouse.get_pos()

        for i, z in enumerate(self.zones):
            iy = list_y + i * item_h - self.scroll
            if iy + item_h < clip.y or iy > clip.bottom:
                continue
            is_current = (z == self.state.zone_name)
            ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h - 2)
            is_hov = ir.collidepoint(mx, my)
            if is_hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=4)
            elif is_current:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=4)
            color = Theme.ACCENT if is_current else Theme.TEXT
            draw_text(surface, z, ir.x + 12, ir.y + 8, color, font)

        surface.set_clip(None)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,
                                                           pygame.K_TAB):
            self.manager.close()
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 30)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            sw, sh = pygame.display.get_surface().get_size()
            rect = self._centered_rect(pygame.display.get_surface(),
                                       500, sh - 120)
            item_h = 32
            list_y = rect.y + 40
            for i, z in enumerate(self.zones):
                iy = list_y + i * item_h - self.scroll
                ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h)
                if ir.collidepoint(event.pos):
                    self.state.load_zone(z)
                    self.manager.close()
                    return True
        return True


# ═════════════════════════════════════════════════════════════════════
#  PrefabPickerModal
# ═════════════════════════════════════════════════════════════════════

class PrefabPickerModal(_BaseModal):
    def __init__(self, manager: ModalManager,
                 place_at: tuple[int, int]):
        super().__init__(manager)
        self.place_at = place_at
        self.prefabs = sorted(get_prefab_defaults().keys())
        self.scroll = 0

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 340, 400)
        self._draw_panel(surface, rect, "Place Entity",
                         border_color=Theme.ENTITY)

        draw_text(surface, "Select a prefab:", rect.x + 16, rect.y + 34,
                  Theme.TEXT_DIM, font_sm)

        item_h = 40
        list_y = rect.y + 56
        mx, my = pygame.mouse.get_pos()
        clip_bottom = rect.bottom - 20

        defaults = get_prefab_defaults()
        for i, prefab in enumerate(self.prefabs):
            iy = list_y + i * item_h - self.scroll
            if iy + item_h < list_y or iy > clip_bottom:
                continue

            ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h - 3)
            is_hov = ir.collidepoint(mx, my)
            bg = Theme.HIGHLIGHT if is_hov else Theme.PANEL
            pygame.draw.rect(surface, bg, ir, border_radius=4)

            pdef = defaults.get(prefab, {})
            sprite = pdef.get("sprite", {})
            char = sprite.get("char", "?")
            color = tuple(sprite.get("color", [200, 200, 200]))
            glyph = font.render(char, True, color)
            surface.blit(glyph, (ir.x + 8, ir.y + 10))

            draw_text(surface, prefab.title(), ir.x + 30, ir.y + 6,
                      Theme.TEXT, font)
            kind = pdef.get("identity", {}).get("kind", "")
            draw_text(surface, f"Kind: {kind}", ir.x + 30, ir.y + 22,
                      Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 30)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            surf = pygame.display.get_surface()
            rect = self._centered_rect(surf, 340, 400)
            item_h = 40
            list_y = rect.y + 56
            for i, prefab in enumerate(self.prefabs):
                iy = list_y + i * item_h - self.scroll
                ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h)
                if ir.collidepoint(event.pos):
                    self._place_entity(prefab)
                    self.manager.close()
                    return True
        return True

    def _place_entity(self, prefab: str):
        r, c = self.place_at
        st = self.state
        defaults = get_prefab_defaults()

        existing_ids = {e.get("id", "") for e in st.entities}
        base = f"{prefab}_{len(st.entities)}"
        uid = base
        n = 0
        while uid in existing_ids:
            n += 1
            uid = f"{base}_{n}"

        pdef = defaults.get(prefab, {})
        ent: dict[str, Any] = {
            "id": uid,
            "prefab": prefab,
            "position": {"x": float(c) + 0.5, "y": float(r) + 0.5},
        }
        if "identity" in pdef:
            ent["identity"] = dict(pdef["identity"])
            ent["identity"]["name"] = f"{prefab.title()} ({uid})"
        if "sprite" in pdef:
            ent["sprite"] = dict(pdef["sprite"])
        if "tile_entity" in pdef:
            ent["tile_entity"] = dict(pdef["tile_entity"])
            ent["tile_entity"]["tiles"] = [[r, c]]
        if "collider" in pdef:
            ent["collider"] = dict(pdef["collider"])
        if "health" in pdef:
            ent["health"] = dict(pdef["health"])
        if "facing" in pdef:
            ent["facing"] = dict(pdef["facing"])
        if "inventory" in pdef:
            import copy
            ent["inventory"] = copy.deepcopy(pdef["inventory"])
        if "dialogue" in pdef:
            ent["dialogue"] = dict(pdef["dialogue"])
        if "wall_sprite" in pdef:
            ent["wall_sprite"] = dict(pdef["wall_sprite"])

        st.entities.append(ent)
        st.selected_entity = len(st.entities) - 1
        st.push_undo()
        st.toast(f"Placed {prefab}: {uid}")


# ═════════════════════════════════════════════════════════════════════
#  AddComponentModal
# ═════════════════════════════════════════════════════════════════════

class AddComponentModal(_BaseModal):
    """Let user add a missing component to the selected entity."""

    COMPONENTS = [
        ("collider", {"w": 0.6, "h": 0.6, "solid": True}),
        ("health", {"current": 100, "maximum": 100}),
        ("tile_entity", {"tile_type": "container"}),
        ("wall_sprite", {"texture_key": "", "width": 1.0,
                         "height": 1.0, "elevation": 0.0}),
        ("inventory", {"items": {}}),
        ("facing", {"direction": "down"}),
        ("dialogue", {"bark": "..."}),
        ("sprite", {"char": "?", "color": [200, 200, 200], "layer": 5}),
    ]

    def __init__(self, manager: ModalManager):
        super().__init__(manager)
        # Filter to only missing components
        st = self.state
        ent = st.entities[st.selected_entity] if 0 <= st.selected_entity < len(st.entities) else None
        self.available = []
        if ent:
            for key, default in self.COMPONENTS:
                if key not in ent:
                    self.available.append((key, default))

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 300, 40 + len(self.available) * 30 + 30)
        self._draw_panel(surface, rect, "Add Component")

        for i, (key, _) in enumerate(self.available):
            iy = rect.y + 40 + i * 30
            ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, 26)
            hov = ir.collidepoint(pygame.mouse.get_pos())
            bg = Theme.HIGHLIGHT if hov else Theme.PANEL
            pygame.draw.rect(surface, bg, ir, border_radius=4)
            draw_text(surface, key.replace("_", " ").title(),
                      ir.x + 12, ir.y + 6, Theme.TEXT, font_sm)

        if not self.available:
            draw_text(surface, "All components present",
                      rect.x + 16, rect.y + 44, Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            surf = pygame.display.get_surface()
            rect = self._centered_rect(surf, 300,
                                       40 + len(self.available) * 30 + 30)
            for i, (key, default) in enumerate(self.available):
                iy = rect.y + 40 + i * 30
                ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, 26)
                if ir.collidepoint(event.pos):
                    st = self.state
                    import copy
                    st.entities[st.selected_entity][key] = copy.deepcopy(default)
                    st.push_undo()
                    st.toast(f"Added: {key}")
                    self.manager.close()
                    return True
        return True


# ═════════════════════════════════════════════════════════════════════
#  PortalWizardModal (3-step portal creation)
# ═════════════════════════════════════════════════════════════════════

class PortalWizardModal(_BaseModal):
    """Multi-step portal creation wizard."""

    STEP_DIR = 1
    STEP_ZONE = 2
    STEP_TILE = 3

    def __init__(self, manager: ModalManager,
                 source_tile: tuple[int, int],
                 editing: dict | None = None):
        super().__init__(manager)
        self.source_tile = source_tile
        self.editing = editing
        self.step = self.STEP_DIR

        # Result
        self.entry_dir = editing.get("exit_direction", "up") if editing else "up"
        self.dest_zone = editing.get("target_zone", "") if editing else ""
        self.dest_tile: tuple[int, int] | None = None
        self.exit_dir = "up"

        if editing:
            tp = editing.get("target_pos", [0, 0])
            self.dest_tile = (int(tp[0]), int(tp[1]))

        # Zone list
        self.zone_list: list[str] = []
        self.zone_scroll = 0

        # Dest map preview
        self.dest_tiles: list[list[int]] | None = None
        self.dest_map_w = 0
        self.dest_map_h = 0
        self.dest_cam_x = 0.0
        self.dest_cam_y = 0.0
        self.dest_zoom = 1.0
        self._panning = False
        self._pan_start = (0, 0)
        self._cam_start = (0.0, 0.0)
        self._dest_hover: tuple[int, int] | None = None

    def _load_dest(self):
        path = ZONES_DIR / f"{self.dest_zone}.json"
        if not path.exists():
            self.dest_tiles = None
            return
        with open(path) as f:
            data = json.load(f)
        self.dest_tiles = data.get("tiles", [])
        self.dest_map_h = len(self.dest_tiles)
        self.dest_map_w = len(self.dest_tiles[0]) if self.dest_tiles else 0
        self.dest_cam_x = -(self.dest_map_w * TILE_SIZE) / 2
        self.dest_cam_y = -(self.dest_map_h * TILE_SIZE) / 2

    def _advance(self):
        self.step += 1
        if self.step == self.STEP_ZONE:
            self.zone_list = list_zones()
        elif self.step == self.STEP_TILE:
            self._load_dest()
        elif self.step > self.STEP_TILE:
            self._finish()

    def _finish(self):
        st = self.state
        r, c = self.source_tile
        dr, dc = self.dest_tile or (0, 0)

        portal = {
            "tiles": [[r, c]],
            "target_zone": self.dest_zone,
            "target_pos": [float(dr), float(dc)],
            "exit_direction": self.entry_dir,
        }

        if self.editing:
            self.editing.update({
                "target_zone": portal["target_zone"],
                "target_pos": portal["target_pos"],
                "exit_direction": portal["exit_direction"],
            })
        else:
            st.portals.append(portal)

        # Return portal in dest zone
        return_portal = {
            "tiles": [[dr, dc]],
            "target_zone": st.zone_name,
            "target_pos": [float(r), float(c)],
            "exit_direction": self.exit_dir,
        }
        st.save_portal_to_dest(return_portal, self.dest_zone, (dr, dc))

        st.push_undo()
        st.toast(f"Portal linked to {self.dest_zone}")
        self.manager.close()

    # ── Drawing ──────────────────────────────────────────────

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)

        if self.step == self.STEP_DIR:
            self._draw_dir_step(surface, font, font_sm)
        elif self.step == self.STEP_ZONE:
            self._draw_zone_step(surface, font, font_sm)
        elif self.step == self.STEP_TILE:
            self._draw_tile_step(surface, font, font_sm)

    def _draw_dir_step(self, surface, font, font_sm):
        rect = self._centered_rect(surface, 460, 220)
        self._draw_panel(surface, rect, "Portal Wizard — Step 1/3",
                         border_color=Theme.PORTAL)

        r, c = self.source_tile
        draw_text(surface, f"Exit direction for portal at ({c}, {r}):",
                  rect.x + 16, rect.y + 44, Theme.TEXT, font_sm)
        draw_text(surface, "Which way does the player walk out?",
                  rect.x + 16, rect.y + 64, Theme.TEXT_DIM, font_sm)

        btn_w, btn_h = 90, 50
        gap = 10
        total = 4 * btn_w + 3 * gap
        bx = rect.x + (rect.w - total) // 2
        by = rect.y + 100
        mx, my = pygame.mouse.get_pos()

        for i, d in enumerate(DIRECTIONS):
            br = pygame.Rect(bx + i * (btn_w + gap), by, btn_w, btn_h)
            hov = br.collidepoint(mx, my)
            sel = (d == self.entry_dir)
            bg = (70, 50, 90) if sel else (Theme.BTN_HOVER if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, br, border_radius=6)
            border = Theme.PORTAL if sel else Theme.BORDER
            pygame.draw.rect(surface, border, br, 2 if sel else 1,
                             border_radius=6)
            arrow = DIR_ARROWS[d]
            draw_text(surface, f"{arrow} {d.title()}", br.x + 8, br.y + 16,
                      Theme.TEXT, font_sm)

    def _draw_zone_step(self, surface, font, font_sm):
        rect = self._centered_rect(surface, 460, 420)
        self._draw_panel(surface, rect, "Portal Wizard — Step 2/3",
                         border_color=Theme.PORTAL)
        draw_text(surface, "Select destination zone:",
                  rect.x + 16, rect.y + 40, Theme.TEXT, font_sm)

        item_h = 36
        list_y = rect.y + 64
        mx, my = pygame.mouse.get_pos()
        clip_bottom = rect.bottom - 40

        for i, z in enumerate(self.zone_list):
            iy = list_y + i * item_h - self.zone_scroll
            if iy + item_h < list_y or iy > clip_bottom:
                continue
            ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h - 3)
            is_hov = ir.collidepoint(mx, my)
            sel = (z == self.dest_zone)
            bg = (60, 40, 80) if sel else (Theme.HIGHLIGHT if is_hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, ir, border_radius=4)
            color = Theme.PORTAL if sel else Theme.TEXT
            draw_text(surface, z, ir.x + 12, ir.y + 10, color, font)

    def _draw_tile_step(self, surface, font, font_sm):
        sw, sh = surface.get_size()
        if not self.dest_tiles:
            draw_text(surface, f"Could not load '{self.dest_zone}'",
                      sw // 2 - 80, sh // 2, Theme.DANGER, font)
            return

        # Draw dest map on left
        map_area_w = sw - 200
        ts = int(TILE_SIZE * self.dest_zoom)
        if ts >= 1:
            map_cx = map_area_w // 2
            map_cy = sh // 2
            for r in range(self.dest_map_h):
                for c in range(self.dest_map_w):
                    wx = c * TILE_SIZE
                    wy = r * TILE_SIZE
                    sx = int((wx + self.dest_cam_x) * self.dest_zoom + map_cx)
                    sy = int((wy + self.dest_cam_y) * self.dest_zoom + map_cy)
                    if sx + ts < 0 or sy + ts < 0 or sx > map_area_w or sy > sh:
                        continue
                    tid = self.dest_tiles[r][c]
                    color = TILE_COLORS.get(tid, (120, 120, 120))
                    tr = pygame.Rect(sx, sy, ts, ts)
                    pygame.draw.rect(surface, color, tr)
                    if ts >= 8:
                        pygame.draw.rect(surface, Theme.GRID, tr, 1)

            # Highlight selected tile
            if self.dest_tile:
                dr, dc = self.dest_tile
                sx = int((dc * TILE_SIZE + self.dest_cam_x) * self.dest_zoom + map_cx)
                sy = int((dr * TILE_SIZE + self.dest_cam_y) * self.dest_zoom + map_cy)
                pygame.draw.rect(surface, Theme.SUCCESS,
                                 (sx, sy, ts, ts), 3)

            # Hover
            if self._dest_hover:
                hr, hc = self._dest_hover
                sx = int((hc * TILE_SIZE + self.dest_cam_x) * self.dest_zoom + map_cx)
                sy = int((hr * TILE_SIZE + self.dest_cam_y) * self.dest_zoom + map_cy)
                hover_surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
                hover_surf.fill((255, 255, 255, 50))
                surface.blit(hover_surf, (sx, sy))

        # Right panel
        panel_x = sw - 200
        pygame.draw.rect(surface, Theme.PANEL, (panel_x, 0, 200, sh))
        pygame.draw.line(surface, Theme.BORDER, (panel_x, 0), (panel_x, sh))

        draw_text(surface, "Step 3/3", panel_x + 12, 10, Theme.PORTAL, font)
        draw_text(surface, f"Zone: {self.dest_zone}",
                  panel_x + 12, 30, Theme.ACCENT, font_sm)
        draw_text(surface, "Click map to pick", panel_x + 12, 50,
                  Theme.TEXT_DIM, font_sm)
        draw_text(surface, "target tile.", panel_x + 12, 66,
                  Theme.TEXT_DIM, font_sm)

        if self.dest_tile:
            dr, dc = self.dest_tile
            draw_text(surface, f"Target: ({dc}, {dr})",
                      panel_x + 12, 100, Theme.SUCCESS, font)
        else:
            draw_text(surface, "Target: (none)",
                      panel_x + 12, 100, Theme.TEXT_DIM, font)

        draw_text(surface, "Exit direction:", panel_x + 12, 140,
                  Theme.TEXT, font_sm)
        draw_text(surface, "(walk-out on dest):", panel_x + 12, 156,
                  Theme.TEXT_DIM, font_sm)

        # Direction buttons
        dir_x = panel_x + 10
        dir_y = 200
        btn_w, btn_h = 80, 40
        gap = 8
        mx, my = pygame.mouse.get_pos()

        for i, d in enumerate(DIRECTIONS):
            by = dir_y + i * (btn_h + gap)
            br = pygame.Rect(dir_x, by, btn_w, btn_h)
            hov = br.collidepoint(mx, my)
            sel = (d == self.exit_dir)
            bg = (60, 40, 80) if sel else (Theme.BTN_HOVER if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, br, border_radius=6)
            border = Theme.PORTAL if sel else Theme.BORDER
            pygame.draw.rect(surface, border, br, 2 if sel else 1,
                             border_radius=6)
            draw_text(surface, f"{DIR_ARROWS[d]} {d.title()}",
                      br.x + 6, br.y + 12, Theme.TEXT, font_sm)

        # Done button
        done_y = dir_y + 4 * (btn_h + gap) + 20
        done_enabled = self.dest_tile is not None
        done_bg = (40, 120, 60) if done_enabled else (50, 50, 55)
        done_r = pygame.Rect(dir_x, done_y, 120, 44)
        if done_r.collidepoint(mx, my) and done_enabled:
            done_bg = (50, 160, 80)
        pygame.draw.rect(surface, done_bg, done_r, border_radius=8)
        pygame.draw.rect(surface,
                         Theme.SUCCESS if done_enabled else Theme.BORDER,
                         done_r, 2, border_radius=8)
        label = "Update" if self.editing else "Create"
        draw_text(surface, f"{label} Portal", done_r.x + 8, done_r.y + 14,
                  Theme.TEXT if done_enabled else Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Revert tile if new portal
            if not self.editing:
                r, c = self.source_tile
                if 0 <= r < self.state.map_h and 0 <= c < self.state.map_w:
                    self.state.tiles[r][c] = 1
            self.manager.close()
            return True

        if self.step == self.STEP_DIR:
            return self._handle_dir_event(event)
        elif self.step == self.STEP_ZONE:
            return self._handle_zone_event(event)
        elif self.step == self.STEP_TILE:
            return self._handle_tile_event(event)
        return True

    def _handle_dir_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            surf = pygame.display.get_surface()
            rect = self._centered_rect(surf, 460, 220)
            btn_w, btn_h = 90, 50
            gap = 10
            total = 4 * btn_w + 3 * gap
            bx = rect.x + (rect.w - total) // 2
            by = rect.y + 100
            for i, d in enumerate(DIRECTIONS):
                br = pygame.Rect(bx + i * (btn_w + gap), by, btn_w, btn_h)
                if br.collidepoint(event.pos):
                    self.entry_dir = d
                    self._advance()
                    return True
        return True

    def _handle_zone_event(self, event) -> bool:
        if event.type == pygame.MOUSEWHEEL:
            self.zone_scroll = max(0, self.zone_scroll - event.y * 30)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            surf = pygame.display.get_surface()
            rect = self._centered_rect(surf, 460, 420)
            item_h = 36
            list_y = rect.y + 64
            for i, z in enumerate(self.zone_list):
                iy = list_y + i * item_h - self.zone_scroll
                ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h)
                if ir.collidepoint(event.pos):
                    self.dest_zone = z
                    self._advance()
                    return True
        return True

    def _handle_tile_event(self, event) -> bool:
        sw, sh = pygame.display.get_surface().get_size()

        if event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                self.dest_zoom = min(4.0, self.dest_zoom * 1.15)
            elif event.y < 0:
                self.dest_zoom = max(0.25, self.dest_zoom / 1.15)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            self._panning = True
            self._pan_start = event.pos
            self._cam_start = (self.dest_cam_x, self.dest_cam_y)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self._panning = False
            return True

        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            # Update hover
            self._dest_hover = self._screen_to_dest_tile(mx, my, sw, sh)
            if self._panning:
                dx = mx - self._pan_start[0]
                dy = my - self._pan_start[1]
                self.dest_cam_x = self._cam_start[0] + dx / self.dest_zoom
                self.dest_cam_y = self._cam_start[1] + dy / self.dest_zoom
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            panel_x = sw - 200

            # Direction buttons
            dir_x = panel_x + 10
            dir_y = 200
            btn_w, btn_h = 80, 40
            gap = 8
            for i, d in enumerate(DIRECTIONS):
                by = dir_y + i * (btn_h + gap)
                br = pygame.Rect(dir_x, by, btn_w, btn_h)
                if br.collidepoint(mx, my):
                    self.exit_dir = d
                    return True

            # Done button
            done_y = dir_y + 4 * (btn_h + gap) + 20
            done_r = pygame.Rect(dir_x, done_y, 120, 44)
            if done_r.collidepoint(mx, my) and self.dest_tile:
                self._advance()
                return True

            # Map click
            rc = self._screen_to_dest_tile(mx, my, sw, sh)
            if rc:
                self.dest_tile = rc
                return True

        return True

    def _screen_to_dest_tile(self, sx, sy, sw, sh):
        if not self.dest_tiles:
            return None
        map_cx = (sw - 200) // 2
        map_cy = sh // 2
        wx = (sx - map_cx) / self.dest_zoom - self.dest_cam_x
        wy = (sy - map_cy) / self.dest_zoom - self.dest_cam_y
        c = int(wx / TILE_SIZE)
        r = int(wy / TILE_SIZE)
        if 0 <= r < self.dest_map_h and 0 <= c < self.dest_map_w:
            return (r, c)
        return None

