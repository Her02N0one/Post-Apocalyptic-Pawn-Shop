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
    """Entity picker that shows both system prefabs AND Forge archetypes."""

    TAB_PREFABS = 0
    TAB_FORGE = 1

    def __init__(self, manager: ModalManager,
                 place_at: tuple[int, int]):
        super().__init__(manager)
        self.place_at = place_at
        self.prefabs = sorted(get_prefab_defaults().keys())
        self.scroll = 0
        self._tab = self.TAB_PREFABS

        # Load Forge archetypes
        try:
            from editor.forge_registry import ForgeRegistry
            reg = ForgeRegistry.instance()
            self._forge_archetypes = sorted(reg.all().values(),
                                            key=lambda a: a.id)
        except Exception:
            self._forge_archetypes = []

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        rect = self._centered_rect(surface, 380, 440)
        self._draw_panel(surface, rect, "Place Entity",
                         border_color=Theme.ENTITY)

        mx, my = pygame.mouse.get_pos()

        # Tab bar
        tab_y = rect.y + 30
        tabs = [("Prefabs", self.TAB_PREFABS), ("Forge", self.TAB_FORGE)]
        tx = rect.x + 10
        self._tab_rects: list[tuple[int, pygame.Rect]] = []
        for label, tab_id in tabs:
            tw = font_sm.size(label)[0] + 20
            tr = pygame.Rect(tx, tab_y, tw, 22)
            is_sel = (self._tab == tab_id)
            hov = tr.collidepoint(mx, my)
            bg = Theme.SELECTED if is_sel else (Theme.HIGHLIGHT if hov else Theme.PANEL)
            pygame.draw.rect(surface, bg, tr, border_radius=4)
            draw_text(surface, label, tx + 10, tab_y + 4,
                      Theme.ACCENT if is_sel else Theme.TEXT_DIM, font_sm)
            self._tab_rects.append((tab_id, tr))
            tx += tw + 4

        # Forge count badge
        if self._forge_archetypes:
            badge = f"({len(self._forge_archetypes)})"
            draw_text(surface, badge, tx + 4, tab_y + 4,
                      Theme.TEXT_DIM, font_sm)

        item_h = 40
        list_y = tab_y + 28
        clip = pygame.Rect(rect.x + 4, list_y, rect.w - 8, rect.bottom - list_y - 10)
        surface.set_clip(clip)

        if self._tab == self.TAB_PREFABS:
            self._draw_prefab_list(surface, font, font_sm, rect,
                                   item_h, list_y, clip.bottom)
        else:
            self._draw_forge_list(surface, font, font_sm, rect,
                                  item_h, list_y, clip.bottom)

        surface.set_clip(None)

    def _draw_prefab_list(self, surface, font, font_sm, rect,
                          item_h, list_y, clip_bottom):
        mx, my = pygame.mouse.get_pos()
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

    def _draw_forge_list(self, surface, font, font_sm, rect,
                         item_h, list_y, clip_bottom):
        mx, my = pygame.mouse.get_pos()
        if not self._forge_archetypes:
            draw_text(surface, "No forge archetypes yet.",
                      rect.x + 16, list_y + 8, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Open Editors \u2192 Entity Forge",
                      rect.x + 16, list_y + 24, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "to create custom entities.",
                      rect.x + 16, list_y + 40, Theme.TEXT_DIM, font_sm)
            return

        kind_icons = {
            "tile": "\u25A3", "box": "\u25A1", "billboard": "\u263A",
        }
        for i, arch in enumerate(self._forge_archetypes):
            iy = list_y + i * item_h - self.scroll
            if iy + item_h < list_y or iy > clip_bottom:
                continue
            ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h - 3)
            is_hov = ir.collidepoint(mx, my)
            bg = Theme.HIGHLIGHT if is_hov else Theme.PANEL
            pygame.draw.rect(surface, bg, ir, border_radius=4)

            icon = kind_icons.get(arch.kind, "?")
            color = arch.sprite_color if arch.kind == "billboard" else arch.color
            glyph = font.render(icon, True, color)
            surface.blit(glyph, (ir.x + 8, ir.y + 10))

            name = arch.display_name or arch.id
            draw_text(surface, name[:24], ir.x + 30, ir.y + 6,
                      Theme.TEXT, font)
            subtitle = f"{arch.kind}"
            if arch.dev_notes:
                subtitle += f"  \u2014 {arch.dev_notes[:30]}"
            draw_text(surface, subtitle, ir.x + 30, ir.y + 22,
                      Theme.TEXT_DIM, font_sm)

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.close()
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 30)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Tab clicks
            for tab_id, tr in getattr(self, '_tab_rects', []):
                if tr.collidepoint(event.pos):
                    self._tab = tab_id
                    self.scroll = 0
                    return True

            surf = pygame.display.get_surface()
            rect = self._centered_rect(surf, 380, 440)
            tab_y = rect.y + 30
            item_h = 40
            list_y = tab_y + 28

            if self._tab == self.TAB_PREFABS:
                for i, prefab in enumerate(self.prefabs):
                    iy = list_y + i * item_h - self.scroll
                    ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h)
                    if ir.collidepoint(event.pos):
                        self._place_prefab(prefab)
                        self.manager.close()
                        return True
            else:
                for i, arch in enumerate(self._forge_archetypes):
                    iy = list_y + i * item_h - self.scroll
                    ir = pygame.Rect(rect.x + 10, iy, rect.w - 20, item_h)
                    if ir.collidepoint(event.pos):
                        self._place_forge_archetype(arch)
                        self.manager.close()
                        return True
        return True

    def _place_prefab(self, prefab: str):
        """Place a system prefab entity."""
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

    def _place_forge_archetype(self, arch):
        """Place a Forge archetype entity."""
        r, c = self.place_at
        st = self.state

        existing_ids = {e.get("id", "") for e in st.entities}
        base = f"{arch.id}_{len(st.entities)}"
        uid = base
        n = 0
        while uid in existing_ids:
            n += 1
            uid = f"{arch.id}_{n}"

        ent: dict[str, Any] = {
            "id": uid,
            "forge_archetype": arch.id,
            "position": {"x": float(c) + 0.5, "y": float(r) + 0.5},
            "identity": {
                "name": arch.display_name or arch.id.replace("_", " ").title(),
                "kind": arch.kind,
            },
            "sprite": {
                "char": arch.sprite_char if arch.kind == "billboard" else (
                    "\u25A3" if arch.kind == "tile" else "\u25A1"),
                "color": list(arch.sprite_color if arch.kind == "billboard"
                              else arch.color),
                "layer": 5,
            },
        }
        if arch.dev_notes:
            ent["dev_notes"] = arch.dev_notes
        if arch.tags:
            ent["tags"] = list(arch.tags)

        # Kind-specific defaults
        if arch.kind == "tile":
            ent["tile_entity"] = {"tile_type": "container",
                                  "tiles": [[r, c]]}
            if arch.texture_key:
                ent["wall_sprite"] = {
                    "texture_key": arch.texture_key,
                    "width": 1.0,
                    "height": arch.ceiling_z - arch.floor_z,
                    "elevation": arch.floor_z,
                }
        elif arch.kind == "box":
            if arch.solid:
                ent["collider"] = {"w": arch.width, "h": arch.depth,
                                   "solid": True}
            if arch.texture_key:
                ent["wall_sprite"] = {
                    "texture_key": arch.texture_key,
                    "width": arch.width,
                    "height": arch.height,
                    "elevation": arch.z_offset,
                }
        elif arch.kind == "billboard":
            if arch.solid:
                ent["collider"] = {"w": 0.4, "h": 0.4, "solid": True}

        st.entities.append(ent)
        st.selected_entity = len(st.entities) - 1
        st.push_undo()
        st.toast(f"Placed {arch.display_name or arch.id}: {uid}")


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


# ═════════════════════════════════════════════════════════════════════
#  TileEditorModal — create / edit ANY tile definition
# ═════════════════════════════════════════════════════════════════════

import os as _os
from pathlib import Path as _Path

from core.tiles import (
    TF, TileDef, TileType, TILE_REGISTRY, TILE_CATEGORIES, TC_CUSTOM,
    TILE_FACE_SLOTS, FACE_WALL_SLOTS, FACE_TOP_SLOT,
    register_tile, update_tile, delete_tile, save_tiles,
    add_category, TILE_TEX_DIR,
    _TYPE_FLAGS, _TYPE_DEFAULT_HEIGHT,
    # Backward-compat aliases so old call-sites don't break
    register_custom_tile, delete_custom_tile, save_custom_tiles,
)

_TILE_TYPES = list(TileType)
_TILE_TYPE_LABELS = [t.value for t in _TILE_TYPES]


class TileEditorModal(_BaseModal):
    """Full tile editor — create, edit, or delete ANY tile.

    Shows a 64x64 texture preview, lets the user browse for a
    texture PNG, export the procedural texture, and manage categories.
    """

    # Extra flag options (not covered by type)
    EXTRA_FLAG_OPTIONS = [
        ("TRANSPARENT", TF.TRANSPARENT, "See-through wall"),
        ("FARMLAND", TF.FARMLAND, "Tillable soil"),
    ]

    def __init__(self, manager: ModalManager,
                 edit_tile: TileDef | None = None,
                 atlas=None):
        super().__init__(manager)
        self._editing = edit_tile
        self._atlas = atlas
        # Form state
        self._name = edit_tile.name if edit_tile else ""
        self._color = list(edit_tile.color) if edit_tile else [120, 120, 120]
        self._tile_type: TileType = edit_tile.type if edit_tile else TileType.FLOOR
        self._extra_flags: TF = TF.NONE
        if edit_tile:
            if edit_tile.transparent:
                self._extra_flags |= TF.TRANSPARENT
            if edit_tile.farmland:
                self._extra_flags |= TF.FARMLAND
        self._texture_key = edit_tile.texture_key or "" if edit_tile else ""
        # face_textures: dict of face_name -> texture_key
        if edit_tile and edit_tile.face_textures:
            self._face_textures: dict[str, str] = dict(edit_tile.face_textures)
        else:
            self._face_textures = {}
        self._height_scale = edit_tile.height_scale if edit_tile else 1.0
        self._category = edit_tile.category if edit_tile else TC_CUSTOM
        # UI state
        self._name_active = False
        self._tex_active = False
        self._cat_active = False   # free-text category input
        self._cat_open = False
        self._cat_text = ""        # typed category (for "new category")
        self._error: str = ""
        self._tex_preview: pygame.Surface | None = None
        self._build_preview()

    def _build_preview(self):
        """Build the 64x64 texture preview from the atlas."""
        if self._atlas and self._editing:
            try:
                self._tex_preview = self._atlas.get(self._editing.id).copy()
            except Exception:
                self._tex_preview = None
        else:
            self._tex_preview = None

    def _tex_file_path(self) -> str:
        """Return the expected texture PNG path for current texture_key."""
        key = self._texture_key.strip()
        if not key:
            return ""
        return _os.path.join(TILE_TEX_DIR, f"{key}.png")

    def _tex_file_exists(self) -> bool:
        p = self._tex_file_path()
        return bool(p and _os.path.exists(p))

    # ── drawing ──────────────────────────────────────────────────

    def draw(self, surface, font, font_sm, dt):
        super().draw(surface, font, font_sm, dt)
        W, H = 400, 620
        rect = self._centered_rect(surface, W, H)
        title = f"Edit Tile (ID {self._editing.id})" if self._editing else "New Tile"
        self._draw_panel(surface, rect, title)

        x0 = rect.x + 16
        y = rect.y + 38
        rw = rect.w - 32
        mx, my = pygame.mouse.get_pos()

        # ── Texture preview (64x64) ─────────────────────────────
        prev_r = pygame.Rect(x0, y, 64, 64)
        pygame.draw.rect(surface, (30, 30, 35), prev_r)
        if self._tex_preview:
            surface.blit(self._tex_preview, prev_r.topleft)
        else:
            # Fallback: draw colour swatch
            pygame.draw.rect(surface, tuple(self._color),
                             prev_r.inflate(-4, -4))
        pygame.draw.rect(surface, Theme.BORDER, prev_r, 1)

        # File path info beside preview
        tx = x0 + 72
        key = self._texture_key.strip() or "—"
        exists = self._tex_file_exists()
        file_col = Theme.SUCCESS if exists else Theme.TEXT_DIM
        draw_text(surface, f"tex: {key}.png", tx, y + 2, file_col, font_sm)
        status = "found" if exists else "not found (procedural)"
        draw_text(surface, status, tx, y + 16, file_col, font_sm)

        self._export_rect = pygame.Rect(0, 0, 0, 0)  # disabled

        # Import button
        imp_r = pygame.Rect(tx, y + 34, 110, 22)
        ihov = imp_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if ihov else Theme.PANEL_LITE,
                         imp_r, border_radius=3)
        pygame.draw.rect(surface, Theme.ACCENT2 if Theme.ACCENT2 else Theme.ACCENT,
                         imp_r, 1, border_radius=3)
        draw_text(surface, "Import PNG", imp_r.x + 8, imp_r.y + 5,
                  Theme.ACCENT2 if Theme.ACCENT2 else Theme.ACCENT, font_sm)
        self._import_rect = imp_r

        y += 72

        # ── Name ────────────────────────────────────────────────
        draw_text(surface, "Name:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        name_r = pygame.Rect(x0, y, rw, 22)
        bg = (35, 35, 42) if self._name_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, name_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, name_r, 1, border_radius=3)
        disp_name = self._name or "e.g. Mossy Stone"
        nc = Theme.TEXT if self._name else Theme.TEXT_DIM
        draw_text(surface, disp_name, name_r.x + 4, name_r.y + 4, nc, font_sm)
        if self._name_active and pygame.time.get_ticks() % 1000 < 500:
            cx = name_r.x + 4 + font_sm.size(self._name)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, name_r.y + 3), (cx, name_r.y + 19))
        self._name_rect = name_r
        y += 28

        # ── Colour preview + RGB sliders ────────────────────────
        draw_text(surface, "Color:", x0, y, Theme.TEXT_DIM, font_sm)
        swatch_r = pygame.Rect(x0 + 50, y - 2, 24, 18)
        pygame.draw.rect(surface, tuple(self._color), swatch_r,
                         border_radius=3)
        pygame.draw.rect(surface, (80, 80, 80), swatch_r, 1,
                         border_radius=3)
        y += 18
        self._color_slider_rects = []
        for i, label in enumerate(("R", "G", "B")):
            lbl_color = [(200, 80, 80), (80, 200, 80), (80, 80, 200)][i]
            draw_text(surface, label, x0, y + 2, lbl_color, font_sm)
            bar_r = pygame.Rect(x0 + 16, y + 2, rw - 60, 12)
            pygame.draw.rect(surface, Theme.FIELD_BG, bar_r, border_radius=3)
            frac = self._color[i] / 255.0
            fill_r = pygame.Rect(bar_r.x, bar_r.y,
                                 int(bar_r.w * frac), bar_r.h)
            pygame.draw.rect(surface, lbl_color, fill_r, border_radius=3)
            draw_text(surface, str(self._color[i]),
                      bar_r.right + 4, y + 1, Theme.TEXT, font_sm)
            self._color_slider_rects.append((bar_r, i))
            y += 18

        # ── Tile Type (dropdown) ─────────────────────────────────
        y += 4
        draw_text(surface, "Type:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        type_r = pygame.Rect(x0, y, rw, 22)
        pygame.draw.rect(surface, Theme.FIELD_BG, type_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, type_r, 1, border_radius=3)
        draw_text(surface, self._tile_type.value, type_r.x + 6, type_r.y + 4,
                  Theme.TEXT, font_sm)
        draw_text(surface, "\u25BE", type_r.right - 16, type_r.y + 4,
                  Theme.TEXT_DIM, font_sm)
        self._type_rect = type_r
        # Type dropdown items (rendered when open)
        if getattr(self, '_type_open', False):
            for ti, tt in enumerate(_TILE_TYPES):
                ir = pygame.Rect(type_r.x, type_r.bottom + ti * 22,
                                 type_r.w, 22)
                bg = Theme.BTN_HOVER if ir.collidepoint(mx, my) else Theme.PANEL_LITE
                pygame.draw.rect(surface, bg, ir)
                pygame.draw.rect(surface, Theme.BORDER, ir, 1)
                draw_text(surface, tt.value, ir.x + 6, ir.y + 4,
                          Theme.TEXT, font_sm)
        y += 28

        # ── Extra flags (TRANSPARENT, FARMLAND) ─────────────────
        self._flag_rects = []
        col_w = rw // 2
        for idx, (fname, fval, fdesc) in enumerate(self.EXTRA_FLAG_OPTIONS):
            col = idx % 2
            if col == 0:
                row_y = y
            fx = x0 + col * col_w
            fy = row_y
            cb_r = pygame.Rect(fx, fy, 14, 14)
            checked = bool(self._extra_flags & fval)
            bg = Theme.ACCENT if checked else Theme.FIELD_BG
            pygame.draw.rect(surface, bg, cb_r, border_radius=2)
            pygame.draw.rect(surface, Theme.BORDER, cb_r, 1, border_radius=2)
            if checked:
                draw_text(surface, "\u2713", cb_r.x + 2, cb_r.y, (255, 255, 255), font_sm)
            draw_text(surface, fname, fx + 18, fy + 1, Theme.TEXT, font_sm)
            self._flag_rects.append((cb_r, fval))
            if col == 1:
                y += 20
        if len(self.EXTRA_FLAG_OPTIONS) % 2 == 1:
            y += 20
        y += 4

        # ── Texture key ─────────────────────────────────────────
        draw_text(surface, "Texture Key:", x0, y, Theme.TEXT_DIM, font_sm)
        y += 16
        tex_r = pygame.Rect(x0, y, rw, 22)
        bg = (35, 35, 42) if self._tex_active else Theme.FIELD_BG
        pygame.draw.rect(surface, bg, tex_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, tex_r, 1, border_radius=3)
        disp_tex = self._texture_key or "e.g. mossy_stone"
        tc = Theme.TEXT if self._texture_key else Theme.TEXT_DIM
        draw_text(surface, disp_tex, tex_r.x + 4, tex_r.y + 4, tc, font_sm)
        if self._tex_active and pygame.time.get_ticks() % 1000 < 500:
            cx = tex_r.x + 4 + font_sm.size(self._texture_key)[0]
            pygame.draw.line(surface, Theme.ACCENT,
                             (cx, tex_r.y + 3), (cx, tex_r.y + 19))
        self._tex_rect = tex_r
        y += 26

        # ── Face textures (slots depend on tile type) ───────────
        slots = TILE_FACE_SLOTS.get(self._tile_type, ())
        _FACE_LABELS = {
            "north": "North", "south": "South",
            "east": "East", "west": "West", "top": "Top",
        }
        if not hasattr(self, '_face_rects'):
            self._face_rects: dict[str, pygame.Rect] = {}
        if not hasattr(self, '_face_active'):
            self._face_active: str = ""  # which face field has focus
        self._face_rects.clear()

        if slots:
            draw_text(surface, "Face Textures:", x0, y, Theme.TEXT_DIM, font_sm)
            y += 16
            for face in slots:
                label = _FACE_LABELS.get(face, face)
                draw_text(surface, f"  {label}:", x0, y, Theme.TEXT_DIM, font_sm)
                fr = pygame.Rect(x0 + 55, y - 2, rw - 55, 20)
                is_active = (self._face_active == face)
                bg = (35, 35, 42) if is_active else Theme.FIELD_BG
                pygame.draw.rect(surface, bg, fr, border_radius=3)
                pygame.draw.rect(surface, Theme.BORDER, fr, 1, border_radius=3)
                val = self._face_textures.get(face, "")
                disp = val or "(default)"
                tc = Theme.TEXT if val else Theme.TEXT_DIM
                draw_text(surface, disp, fr.x + 4, fr.y + 3, tc, font_sm)
                if is_active and pygame.time.get_ticks() % 1000 < 500:
                    cx = fr.x + 4 + font_sm.size(val)[0]
                    pygame.draw.line(surface, Theme.ACCENT,
                                     (cx, fr.y + 2), (cx, fr.y + 17))
                self._face_rects[face] = fr
                y += 22
            y += 4

        # ── Height scale ────────────────────────────────────────
        draw_text(surface, "Height:", x0, y, Theme.TEXT_DIM, font_sm)
        hs_bar = pygame.Rect(x0 + 60, y + 2, rw - 100, 12)
        pygame.draw.rect(surface, Theme.FIELD_BG, hs_bar, border_radius=3)
        frac = min(1.0, self._height_scale)
        fill_r = pygame.Rect(hs_bar.x, hs_bar.y,
                             int(hs_bar.w * frac), hs_bar.h)
        pygame.draw.rect(surface, Theme.ACCENT, fill_r, border_radius=3)
        draw_text(surface, f"{self._height_scale:.2f}",
                  hs_bar.right + 4, y, Theme.TEXT, font_sm)
        self._hs_rect = hs_bar
        y += 22

        # ── Category (dropdown + free-text for new) ─────────────
        draw_text(surface, "Category:", x0, y, Theme.TEXT_DIM, font_sm)
        cat_r = pygame.Rect(x0 + 80, y - 2, rw - 80, 22)
        hov = cat_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.FIELD_BG,
                         cat_r, border_radius=3)
        pygame.draw.rect(surface, Theme.BORDER, cat_r, 1, border_radius=3)
        if self._cat_active:
            disp_cat = self._cat_text or "type new category..."
            cc = Theme.TEXT if self._cat_text else Theme.TEXT_DIM
            draw_text(surface, disp_cat, cat_r.x + 6, cat_r.y + 4, cc, font_sm)
            if pygame.time.get_ticks() % 1000 < 500:
                cx = cat_r.x + 6 + font_sm.size(self._cat_text)[0]
                pygame.draw.line(surface, Theme.ACCENT,
                                 (cx, cat_r.y + 3), (cx, cat_r.y + 19))
        else:
            draw_text(surface, self._category, cat_r.x + 6, cat_r.y + 4,
                      Theme.TEXT, font_sm)
            draw_text(surface, "\u25be", cat_r.right - 14, cat_r.y + 4,
                      Theme.TEXT_DIM, font_sm)
        self._cat_rect = cat_r
        y += 28

        # Category dropdown overlay
        if self._cat_open:
            cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
            dy = cat_r.bottom
            for ci, cname in enumerate(cat_items):
                cr = pygame.Rect(cat_r.x, dy + ci * 22, cat_r.w, 22)
                chov = cr.collidepoint(mx, my)
                pygame.draw.rect(surface,
                                 Theme.HIGHLIGHT if chov else Theme.PANEL, cr)
                pygame.draw.rect(surface, Theme.BORDER, cr, 1)
                if cname.startswith("+"):
                    col = Theme.ACCENT2
                else:
                    col = Theme.ACCENT if cname == self._category else Theme.TEXT
                draw_text(surface, cname, cr.x + 6, cr.y + 4, col, font_sm)

        # ── Error message ───────────────────────────────────────
        if self._error:
            draw_text(surface, self._error, x0, y, Theme.DANGER, font_sm)
            y += 16

        # ── Action buttons ──────────────────────────────────────
        y = rect.bottom - 40
        # Save/Create button
        save_r = pygame.Rect(x0, y, 100, 28)
        hov = save_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         save_r, border_radius=5)
        pygame.draw.rect(surface, Theme.SUCCESS, save_r, 1, border_radius=5)
        save_label = "Update" if self._editing else "Create"
        draw_text(surface, save_label,
                  save_r.x + 20, save_r.y + 7, Theme.SUCCESS, font_sm)
        self._save_rect = save_r

        # Delete button (available for ANY tile when editing)
        if self._editing:
            del_r = pygame.Rect(save_r.right + 12, y, 80, 28)
            hov = del_r.collidepoint(mx, my)
            pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                             del_r, border_radius=5)
            pygame.draw.rect(surface, Theme.DANGER, del_r, 1, border_radius=5)
            draw_text(surface, "Delete",
                      del_r.x + 16, del_r.y + 7, Theme.DANGER, font_sm)
            self._del_rect = del_r
        else:
            self._del_rect = pygame.Rect(0, 0, 0, 0)

        # Cancel
        cancel_r = pygame.Rect(rect.right - 90, y, 74, 28)
        hov = cancel_r.collidepoint(mx, my)
        pygame.draw.rect(surface, Theme.BTN_HOVER if hov else Theme.PANEL_LITE,
                         cancel_r, border_radius=5)
        pygame.draw.rect(surface, Theme.BORDER, cancel_r, 1, border_radius=5)
        draw_text(surface, "Cancel",
                  cancel_r.x + 14, cancel_r.y + 7, Theme.TEXT, font_sm)
        self._cancel_rect = cancel_r

    # ── events ───────────────────────────────────────────────────

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if getattr(self, '_type_open', False):
                    self._type_open = False
                    return True
                if self._cat_open:
                    self._cat_open = False
                    return True
                if self._cat_active:
                    self._cat_active = False
                    return True
                self.manager.close()
                return True

            # Category free-text input
            if self._cat_active:
                if event.key == pygame.K_BACKSPACE:
                    self._cat_text = self._cat_text[:-1]
                elif event.key == pygame.K_RETURN:
                    if self._cat_text.strip():
                        new_cat = self._cat_text.strip()
                        add_category(new_cat)
                        self._category = new_cat
                    self._cat_active = False
                    self._cat_text = ""
                elif event.key == pygame.K_TAB:
                    self._cat_active = False
                elif event.unicode and event.unicode.isprintable():
                    self._cat_text += event.unicode
                return True

            # Text input for name / texture / front / floor fields
            if self._name_active:
                if event.key == pygame.K_BACKSPACE:
                    self._name = self._name[:-1]
                elif event.key == pygame.K_RETURN:
                    self._name_active = False
                elif event.key == pygame.K_TAB:
                    self._name_active = False
                    self._tex_active = True
                elif event.unicode and event.unicode.isprintable():
                    self._name += event.unicode
                return True

            if self._tex_active:
                if event.key == pygame.K_BACKSPACE:
                    self._texture_key = self._texture_key[:-1]
                elif event.key == pygame.K_RETURN:
                    self._tex_active = False
                elif event.key == pygame.K_TAB:
                    self._tex_active = False
                    # Tab into first face slot if available
                    slots = TILE_FACE_SLOTS.get(self._tile_type, ())
                    if slots:
                        self._face_active = slots[0]
                elif event.unicode and event.unicode.isprintable():
                    self._texture_key += event.unicode
                return True

            if getattr(self, '_face_active', ''):
                face = self._face_active
                val = self._face_textures.get(face, "")
                if event.key == pygame.K_BACKSPACE:
                    self._face_textures[face] = val[:-1]
                    if not self._face_textures[face]:
                        self._face_textures.pop(face, None)
                elif event.key in (pygame.K_RETURN, pygame.K_TAB):
                    # Move to next face slot or done
                    slots = TILE_FACE_SLOTS.get(self._tile_type, ())
                    idx = list(slots).index(face) if face in slots else -1
                    if event.key == pygame.K_TAB and idx + 1 < len(slots):
                        self._face_active = slots[idx + 1]
                    else:
                        self._face_active = ""
                elif event.unicode and event.unicode.isprintable():
                    self._face_textures[face] = val + event.unicode
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            self._error = ""

            # Type dropdown items
            if getattr(self, '_type_open', False):
                type_r = self._type_rect
                for ti, tt in enumerate(_TILE_TYPES):
                    ir = pygame.Rect(type_r.x, type_r.bottom + ti * 22,
                                     type_r.w, 22)
                    if ir.collidepoint(mx, my):
                        self._tile_type = tt
                        # Update height default when type changes
                        self._height_scale = _TYPE_DEFAULT_HEIGHT.get(tt, 1.0)
                        self._type_open = False
                        return True
                self._type_open = False
                return True

            # Category dropdown
            if self._cat_open:
                cat_items = list(TILE_CATEGORIES) + ["+ New Category..."]
                cat_r = self._cat_rect
                dy = cat_r.bottom
                for ci, cname in enumerate(cat_items):
                    cr = pygame.Rect(cat_r.x, dy + ci * 22, cat_r.w, 22)
                    if cr.collidepoint(mx, my):
                        if cname.startswith("+"):
                            self._cat_active = True
                            self._cat_text = ""
                        else:
                            self._category = cname
                        self._cat_open = False
                        return True
                self._cat_open = False
                return True

            # Type dropdown toggle
            if hasattr(self, '_type_rect') and self._type_rect.collidepoint(mx, my):
                self._type_open = not getattr(self, '_type_open', False)
                return True

            # Name field
            if hasattr(self, '_name_rect') and self._name_rect.collidepoint(mx, my):
                self._name_active = True
                self._tex_active = False
                self._ft_active = False
                self._fl_active = False
                self._cat_active = False
                return True
            else:
                self._name_active = False

            # Texture field
            if hasattr(self, '_tex_rect') and self._tex_rect.collidepoint(mx, my):
                self._tex_active = True
                self._name_active = False
                self._face_active = ""
                self._cat_active = False
                return True
            else:
                self._tex_active = False

            # Face texture fields
            face_clicked = False
            for face, fr in getattr(self, '_face_rects', {}).items():
                if fr.collidepoint(mx, my):
                    self._face_active = face
                    self._name_active = False
                    self._tex_active = False
                    self._cat_active = False
                    face_clicked = True
                    break
            if face_clicked:
                return True
            else:
                self._face_active = ""

            # Colour sliders
            for bar_r, ci in getattr(self, '_color_slider_rects', []):
                if bar_r.collidepoint(mx, my):
                    frac = (mx - bar_r.x) / max(1, bar_r.w)
                    self._color[ci] = max(0, min(255, int(frac * 255)))
                    return True

            # Height scale slider
            if hasattr(self, '_hs_rect') and self._hs_rect.collidepoint(mx, my):
                frac = (mx - self._hs_rect.x) / max(1, self._hs_rect.w)
                self._height_scale = round(max(0.05, min(1.0, frac)), 2)
                return True

            # Extra flag checkboxes (TRANSPARENT, FARMLAND)
            for cb_r, fval in getattr(self, '_flag_rects', []):
                if cb_r.collidepoint(mx, my):
                    self._extra_flags ^= fval
                    return True

            # Category dropdown toggle
            if hasattr(self, '_cat_rect') and self._cat_rect.collidepoint(mx, my):
                if not self._cat_active:
                    self._cat_open = not self._cat_open
                return True

            # Import PNG button
            if hasattr(self, '_import_rect') and self._import_rect.collidepoint(mx, my):
                self._do_import()
                return True

            # Save / Create
            if hasattr(self, '_save_rect') and self._save_rect.collidepoint(mx, my):
                return self._do_save()

            # Delete
            if hasattr(self, '_del_rect') and self._del_rect.collidepoint(mx, my):
                if self._editing:
                    delete_tile(self._editing.id)
                    self.state.toast(f"Deleted tile: {self._editing.name}")
                    self.manager.close()
                return True

            # Cancel
            if hasattr(self, '_cancel_rect') and self._cancel_rect.collidepoint(mx, my):
                self.manager.close()
                return True

        # Dragging on colour sliders
        if event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            mx, my = event.pos
            for bar_r, ci in getattr(self, '_color_slider_rects', []):
                if bar_r.collidepoint(mx, my):
                    frac = (mx - bar_r.x) / max(1, bar_r.w)
                    self._color[ci] = max(0, min(255, int(frac * 255)))
                    return True
            if hasattr(self, '_hs_rect') and self._hs_rect.collidepoint(mx, my):
                frac = (mx - self._hs_rect.x) / max(1, self._hs_rect.w)
                self._height_scale = round(max(0.05, min(1.0, frac)), 2)
                return True

        return True  # consume all events while modal is open

    def _do_import(self):
        """Open file dialog to import an image as the tile's texture."""
        tile_id = self._editing.id if self._editing else None
        key = self._texture_key.strip() or None
        try:
            from systems.textures import browse_and_import
            dest = browse_and_import(tile_id=tile_id, key=key)
            if dest:
                self.state.toast(f"Imported: {_os.path.basename(str(dest))}")
                # If no texture key was set, pre-fill from imported filename
                if not self._texture_key.strip():
                    self._texture_key = dest.stem
                # Invalidate atlas cache and rebuild preview
                if self._atlas and tile_id:
                    self._atlas.invalidate(tile_id)
                self._build_preview()
            # else: user cancelled — no-op
        except Exception as exc:
            self._error = f"Import failed: {exc}"

    def _do_save(self) -> bool:
        name = self._name.strip()
        if not name:
            self._error = "Name is required."
            return True
        color = (self._color[0], self._color[1], self._color[2])
        tex = self._texture_key.strip() or name.lower().replace(" ", "_")
        # Compute flags: base from type + extra toggles
        flags = _TYPE_FLAGS.get(self._tile_type, TF.NONE) | self._extra_flags

        # Build clean face_textures dict (strip empty values)
        ft_clean = {k: v.strip() for k, v in self._face_textures.items()
                     if v.strip()}

        if self._editing:
            # Update existing tile (works for ANY tile)
            update_tile(
                self._editing.id,
                name=name, color=color,
                type=self._tile_type, flags=flags,
                texture_key=tex,
                face_textures=ft_clean,
                height_scale=self._height_scale,
                category=self._category,
            )
            # Invalidate atlas cache for this tile
            if self._atlas:
                self._atlas.invalidate(self._editing.id)
            self.state.toast(f"Updated tile: {name} (ID {self._editing.id})")
        else:
            td = register_tile(
                name=name, color=color,
                tile_type=self._tile_type, flags=flags,
                texture_key=tex,
                face_textures=ft_clean,
                height_scale=self._height_scale,
                category=self._category,
            )
            self.state.toast(f"Created tile: {name} (ID {td.id})")

        self.manager.close()
        return True


# Backward-compat alias
CustomTileModal = TileEditorModal

