"""editor/templates.py — Zone template system.

Allows creation of zone *templates* with rectangular *slots* that can be
filled with different *room* variants at bake-time.  This gives variety
(e.g.  apartment complexes where every unit differs) while keeping a
consistent overall layout.

Data model
----------
**Template** (``templates/<name>.json``)::

    {
        "name": "apartment_block",
        "width": 50, "height": 40,
        "base_tiles": [[int, ...]],           # fixed tile grid
        "slots": [
            {
                "name": "unit_a", "x": 5, "y": 5, "w": 10, "h": 8,
                "tags": ["bedroom"],           # room variant filter
                "required": true
            }, ...
        ],
        "fixed_entities": [ {...}, ... ],      # always-present entities
        "portals": [ {...}, ... ]              # always-present portals
    }

**Room variant** (``templates/rooms/<name>.json``)::

    {
        "name": "cozy_bedroom",
        "tags": ["bedroom"],
        "width": 10, "height": 8,
        "tiles": [[int, ...]],
        "entities": [ {...}, ... ]
    }

**Baking** picks a random room for each slot and merges tiles/entities
into a concrete zone that can be saved as a normal zone JSON.
"""

from __future__ import annotations

import json
import os
import random
from copy import deepcopy
from typing import Any

import pygame

from editor.state import EditorState, TEMPLATES_DIR, ROOMS_DIR
from editor.ui import (
    Theme, UIContext, Button, TextField,
    draw_text,
)


# ── I/O helpers ──────────────────────────────────────────────────

def list_templates() -> list[str]:
    """Return template names (without extension) from templates/."""
    if not os.path.isdir(TEMPLATES_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(TEMPLATES_DIR)
        if f.endswith(".json")
    )


def load_template(name: str) -> dict[str, Any] | None:
    p = os.path.join(TEMPLATES_DIR, f"{name}.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_template(name: str, data: dict[str, Any]) -> bool:
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    p = os.path.join(TEMPLATES_DIR, f"{name}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def list_rooms() -> list[str]:
    """Return room variant names."""
    if not os.path.isdir(ROOMS_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(ROOMS_DIR)
        if f.endswith(".json")
    )


def load_room(name: str) -> dict[str, Any] | None:
    p = os.path.join(ROOMS_DIR, f"{name}.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_room(name: str, data: dict[str, Any]) -> bool:
    os.makedirs(ROOMS_DIR, exist_ok=True)
    p = os.path.join(ROOMS_DIR, f"{name}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def delete_room(name: str) -> bool:
    p = os.path.join(ROOMS_DIR, f"{name}.json")
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


# ── Baking ───────────────────────────────────────────────────────

def bake_template(template: dict[str, Any],
                  seed: int | None = None) -> dict[str, Any]:
    """Convert a template into a concrete zone dict.

    For each slot the baking process:
    1. Gathers all rooms whose tags intersect the slot's tags.
    2. Filters by size (must be <= slot size).
    3. Picks one at random (using *seed* for reproducibility).
    4. Pastes the room's tiles into the base grid (centered in slot).
    5. Appends the room's entities with offset positions.

    Returns a zone dict ready for ``EditorState.load_zone()`` or saving.
    """
    rng = random.Random(seed)
    w = template["width"]
    h = template["height"]

    # Deep-copy base tiles (or create empty)
    base = template.get("base_tiles")
    if base:
        tiles = [row[:] for row in base]
    else:
        tiles = [[0] * w for _ in range(h)]

    entities = deepcopy(template.get("fixed_entities", []))
    portals = deepcopy(template.get("portals", []))
    anchor = template.get("anchor", [w // 2, h // 2])

    # Load all room variants
    room_cache: dict[str, dict] = {}
    for rn in list_rooms():
        rd = load_room(rn)
        if rd:
            room_cache[rn] = rd

    for slot in template.get("slots", []):
        sx, sy, sw, sh_ = slot["x"], slot["y"], slot["w"], slot["h"]
        slot_tags = set(slot.get("tags", []))
        required = slot.get("required", True)

        # Find candidates
        candidates = []
        for rn, rd in room_cache.items():
            room_tags = set(rd.get("tags", []))
            rw, rh = rd.get("width", 0), rd.get("height", 0)
            if rw > sw or rh > sh_:
                continue
            if slot_tags and room_tags and not (slot_tags & room_tags):
                continue
            candidates.append((rn, rd))

        if not candidates:
            if required:
                # Fill slot with floor (tile 1)
                for row in range(sy, min(sy + sh_, h)):
                    for col in range(sx, min(sx + sw, w)):
                        tiles[row][col] = 1
            continue

        rn, rd = rng.choice(candidates)
        rw = rd.get("width", sw)
        rh = rd.get("height", sh_)

        # Center room in slot
        ox = sx + (sw - rw) // 2
        oy = sy + (sh_ - rh) // 2

        # Paste tiles
        room_tiles = rd.get("tiles", [])
        for ry, row in enumerate(room_tiles):
            ty = oy + ry
            if 0 <= ty < h:
                for rx, tile_id in enumerate(row):
                    tx = ox + rx
                    if 0 <= tx < w:
                        tiles[ty][tx] = tile_id

        # Merge entities with offset
        for ent in rd.get("entities", []):
            e = deepcopy(ent)
            if "position" in e:
                pos = e["position"]
                if isinstance(pos, list) and len(pos) >= 2:
                    pos[0] += ox
                    pos[1] += oy
                elif isinstance(pos, dict):
                    pos["x"] = pos.get("x", 0) + ox
                    pos["y"] = pos.get("y", 0) + oy
            entities.append(e)

    return {
        "name": template.get("name", "baked_zone"),
        "width": w,
        "height": h,
        "anchor": anchor,
        "tiles": tiles,
        "entities": entities,
        "portals": portals,
        "first_person": template.get("first_person", False),
    }


# ── Template Editor Panel ────────────────────────────────────────

class TemplateEditor:
    """Full-screen template editor overlay."""

    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self.active = False

        self.template_name: str = ""
        self.template: dict[str, Any] | None = None
        self.slots: list[dict] = []
        self.selected_slot: int = -1
        self.scroll = 0

        # Buttons
        self.btn_close = Button(pygame.Rect(0, 0, 70, 28), "Close",
                                color=Theme.PANEL_LITE)
        self.btn_save = Button(pygame.Rect(0, 0, 70, 28), "Save",
                               color=(40, 80, 40),
                               text_color=Theme.SUCCESS)
        self.btn_bake = Button(pygame.Rect(0, 0, 110, 28),
                               "Bake Zone",
                               color=(60, 40, 80),
                               text_color=Theme.ACCENT2)
        self.btn_new_slot = Button(pygame.Rect(0, 0, 100, 24),
                                   "Add Slot", color=Theme.PANEL_LITE)
        self.btn_from_zone = Button(pygame.Rect(0, 0, 140, 28),
                                    "From Current Zone",
                                    color=Theme.PANEL_LITE)
        self.btn_export_room = Button(pygame.Rect(0, 0, 120, 24),
                                      "Export Room",
                                      color=Theme.PANEL_LITE)

        # New template dialog
        self._new_name_field: TextField | None = None
        # Room tag editor
        self._tag_field: TextField | None = None

    def open(self):
        self.active = True
        self._refresh_template_list()

    def close(self):
        self.active = False
        self.ctx.release_focus()

    def _refresh_template_list(self):
        self._template_names = list_templates()

    # ── Template creation from current zone ──────────────────

    def from_current_zone(self) -> dict[str, Any]:
        """Create a template dict from the current zone state."""
        s = self.state
        return {
            "name": s.zone_name or "untitled",
            "width": s.map_w,
            "height": s.map_h,
            "base_tiles": [row[:] for row in s.tiles],
            "slots": [],
            "fixed_entities": deepcopy(s.entities),
            "portals": deepcopy(s.portals),
            "first_person": s.first_person,
        }

    # ── Export selection as room ────────────────────────────

    def export_room_from_selection(self, name: str, x: int, y: int,
                                   w: int, h: int,
                                   tags: list[str]) -> bool:
        """Extract a rectangular region from the zone as a room variant."""
        s = self.state
        tiles = []
        for row in range(y, min(y + h, s.map_h)):
            r = []
            for col in range(x, min(x + w, s.map_w)):
                r.append(s.tiles[row][col])
            tiles.append(r)

        # Entities inside the region
        ents = []
        for e in s.entities:
            pos = e.get("position")
            if isinstance(pos, list) and len(pos) >= 2:
                ex, ey = pos[0], pos[1]
            elif isinstance(pos, dict):
                ex, ey = pos.get("x", 0), pos.get("y", 0)
            else:
                continue
            if x <= ex < x + w and y <= ey < y + h:
                ec = deepcopy(e)
                if isinstance(ec["position"], list):
                    ec["position"][0] -= x
                    ec["position"][1] -= y
                elif isinstance(ec["position"], dict):
                    ec["position"]["x"] -= x
                    ec["position"]["y"] -= y
                ents.append(ec)

        room = {
            "name": name,
            "tags": tags,
            "width": w,
            "height": h,
            "tiles": tiles,
            "entities": ents,
        }
        return save_room(name, room)

    # ── Drawing ──────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if not self.active:
            return

        sw, sh = surface.get_size()
        surface.fill(Theme.BG)

        # Header
        pygame.draw.rect(surface, Theme.PANEL, (0, 0, sw, 40))
        pygame.draw.line(surface, Theme.BORDER, (0, 39), (sw, 39))
        draw_text(surface, "ZONE TEMPLATE EDITOR", 16, 10,
                  Theme.ACCENT2, font)

        self.btn_close.rect = pygame.Rect(sw - 80, 6, 70, 28)
        self.btn_close.draw(surface, font_sm)
        self.btn_save.rect = pygame.Rect(sw - 158, 6, 70, 28)
        self.btn_save.draw(surface, font_sm)
        self.btn_bake.rect = pygame.Rect(sw - 278, 6, 110, 28)
        self.btn_bake.draw(surface, font_sm)

        # Left: Template list (200px)
        list_w = 200
        pygame.draw.line(surface, Theme.BORDER, (list_w, 40), (list_w, sh))
        self._draw_template_list(surface, font, font_sm, list_w, sh)

        # Right: Template detail
        if self.template is not None:
            self._draw_template_detail(surface, font, font_sm,
                                       list_w, sw, sh)
        else:
            draw_text(surface, "No template loaded.",
                      list_w + 20, 60, Theme.TEXT_DIM, font)
            self.btn_from_zone.rect = pygame.Rect(list_w + 20, 90,
                                                   160, 28)
            self.btn_from_zone.draw(surface, font_sm)

        # New template dialog
        if self._new_name_field is not None:
            self._draw_new_dialog(surface, font, font_sm, dt)

    def _draw_template_list(self, surface, font, font_sm, lw, sh):
        # New button
        new_r = pygame.Rect(6, 50, lw - 12, 26)
        hov = new_r.collidepoint(*pygame.mouse.get_pos())
        bg = Theme.HIGHLIGHT if hov else Theme.PANEL_LITE
        pygame.draw.rect(surface, bg, new_r, border_radius=4)
        draw_text(surface, "+ New Template", new_r.x + 22, new_r.y + 5,
                  Theme.ACCENT, font_sm)

        y = 86
        mx, my = pygame.mouse.get_pos()
        for tn in self._template_names:
            ir = pygame.Rect(6, y, lw - 12, 26)
            is_sel = (tn == self.template_name)
            hov = ir.collidepoint(mx, my)
            if is_sel:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=4)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=4)
            draw_text(surface, tn, ir.x + 8, ir.y + 5,
                      Theme.ACCENT2 if is_sel else Theme.TEXT, font_sm)
            y += 30

        # Room variants section
        y += 20
        pygame.draw.line(surface, Theme.BORDER, (6, y), (lw - 6, y))
        y += 8
        draw_text(surface, "Room Variants:", 8, y, Theme.ACCENT, font_sm)
        y += 22
        rooms = list_rooms()
        for rn in rooms:
            ir = pygame.Rect(6, y, lw - 12, 22)
            hov = ir.collidepoint(mx, my)
            if hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=3)
            draw_text(surface, f"  {rn}", ir.x, ir.y + 3,
                      Theme.TEXT_DIM, font_sm)
            y += 24

    def _draw_template_detail(self, surface, font, font_sm, lx, sw, sh):
        t = self.template
        px = lx + 12
        w = sw - lx - 24

        draw_text(surface, f"Template: {self.template_name}",
                  px, 50, Theme.ACCENT2, font)
        draw_text(surface, f"Size: {t['width']} x {t['height']}  |  "
                  f"Slots: {len(t.get('slots', []))}  |  "
                  f"Entities: {len(t.get('fixed_entities', []))}",
                  px, 72, Theme.TEXT_DIM, font_sm)

        # Add slot
        self.btn_new_slot.rect = pygame.Rect(px, 96, 100, 24)
        self.btn_new_slot.draw(surface, font_sm)
        # Export room
        self.btn_export_room.rect = pygame.Rect(px + 112, 96, 120, 24)
        self.btn_export_room.draw(surface, font_sm)
        # From current zone
        self.btn_from_zone.rect = pygame.Rect(px + 244, 96, 160, 24)
        self.btn_from_zone.draw(surface, font_sm)

        y = 130 - self.scroll
        slots = t.get("slots", [])
        mx, my = pygame.mouse.get_pos()

        for si, slot in enumerate(slots):
            # Slot header
            sr = pygame.Rect(px, y, w, 26)
            is_sel = (si == self.selected_slot)
            bg = Theme.SELECTED if is_sel else Theme.PANEL_LITE
            pygame.draw.rect(surface, bg, sr, border_radius=4)

            sn = slot.get("name", f"slot_{si}")
            tags = ", ".join(slot.get("tags", []))
            draw_text(surface,
                      f"{sn}  ({slot['w']}x{slot['h']})  "
                      f"@ ({slot['x']},{slot['y']})  "
                      f"tags: [{tags}]",
                      px + 8, y + 5, Theme.TEXT, font_sm)

            # Delete slot
            del_r = pygame.Rect(px + w - 50, y + 4, 40, 18)
            if del_r.collidepoint(mx, my):
                pygame.draw.rect(surface, (80, 30, 30), del_r,
                                 border_radius=2)
            draw_text(surface, "Del", del_r.x + 8, del_r.y + 1,
                      Theme.DANGER, font_sm)

            y += 30

        # Mini preview of base tiles
        y += 10
        preview_h = min(200, sh - y - 30)
        if preview_h > 30:
            tw = t.get("width", 1)
            th = t.get("height", 1)
            scale = min((w - 4) / max(tw, 1),
                        (preview_h - 4) / max(th, 1), 8)
            ox = px + 2
            oy = y + 2
            base = t.get("base_tiles", [])
            for ry, row in enumerate(base):
                for rx, tid in enumerate(row):
                    if tid != 0:
                        c = (60, 50, 40) if tid == 1 else (50, 60, 50)
                        pygame.draw.rect(surface, c,
                                         (int(ox + rx * scale),
                                          int(oy + ry * scale),
                                          max(int(scale), 1),
                                          max(int(scale), 1)))
            # Draw slots as colored rects
            for si, slot in enumerate(slots):
                sx = int(ox + slot["x"] * scale)
                sy = int(oy + slot["y"] * scale)
                ssw = int(slot["w"] * scale)
                ssh = int(slot["h"] * scale)
                is_sel = (si == self.selected_slot)
                color = Theme.ACCENT2 if is_sel else Theme.ACCENT
                pygame.draw.rect(surface, color,
                                 (sx, sy, ssw, ssh), 2)

    def _draw_new_dialog(self, surface, font, font_sm, dt):
        sw, sh = surface.get_size()
        rect = pygame.Rect((sw - 400) // 2, (sh - 100) // 2, 400, 100)
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, Theme.ACCENT2, rect, 2, border_radius=10)
        draw_text(surface, "Template name:", rect.x + 16, rect.y + 14,
                  Theme.TEXT_DIM, font_sm)
        self._new_name_field.rect = pygame.Rect(
            rect.x + 16, rect.y + 38, 368, 28)
        self._new_name_field.draw(surface, font, dt)
        draw_text(surface, "Enter = create  |  Esc = cancel",
                  rect.x + 16, rect.y + 74, Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.active:
            return False

        # New template dialog
        if self._new_name_field is not None:
            return self._handle_new_dialog_event(event)

        if self.btn_close.handle_event(event):
            self.close()
            return True
        if self.btn_save.handle_event(event):
            if self.template and self.template_name:
                save_template(self.template_name, self.template)
                self.state.toast("Template saved!")
                self._refresh_template_list()
            return True
        if self.btn_bake.handle_event(event):
            if self.template:
                zone = bake_template(self.template)
                self.state.load_zone_data(zone)
                self.close()
                self.state.toast("Template baked → loaded as current zone")
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True

        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 30)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            sw, sh = pygame.display.get_surface().get_size()
            list_w = 200

            # From current zone
            if self.btn_from_zone.handle_event(event):
                self.template = self.from_current_zone()
                self.template_name = self.state.zone_name or "untitled"
                self.state.toast("Template created from zone")
                return True

            # New template
            new_r = pygame.Rect(6, 50, list_w - 12, 26)
            if new_r.collidepoint(mx, my):
                self._new_name_field = TextField(
                    pygame.Rect(0, 0, 368, 28), self.ctx,
                    value="", placeholder="template_name")
                self.ctx.take_focus(self._new_name_field.uid)
                return True

            # Template list
            if mx < list_w:
                y = 86
                for tn in self._template_names:
                    ir = pygame.Rect(6, y, list_w - 12, 26)
                    if ir.collidepoint(mx, my):
                        self.template_name = tn
                        self.template = load_template(tn)
                        self.selected_slot = -1
                        return True
                    y += 30
                return True

            # Detail clicks
            if self.template:
                return self._handle_detail_click(mx, my)

        return True

    def _handle_detail_click(self, mx, my) -> bool:
        sw = pygame.display.get_surface().get_width()
        px = 212
        w = sw - 224

        # New slot
        if self.btn_new_slot.rect.collidepoint(mx, my):
            slots = self.template.setdefault("slots", [])
            idx = len(slots)
            slots.append({
                "name": f"slot_{idx}",
                "x": 2, "y": 2, "w": 6, "h": 6,
                "tags": [], "required": True,
            })
            self.state.toast("Slot added")
            return True

        # Export room
        if self.btn_export_room.rect.collidepoint(mx, my):
            if self.selected_slot >= 0 and self.template:
                slots = self.template.get("slots", [])
                if self.selected_slot < len(slots):
                    slot = slots[self.selected_slot]
                    ok = self.export_room_from_selection(
                        f"room_{self.template_name}_{self.selected_slot}",
                        slot["x"], slot["y"], slot["w"], slot["h"],
                        slot.get("tags", []))
                    if ok:
                        self.state.toast("Room exported")
            return True

        # Slot clicks
        y = 130 - self.scroll
        slots = self.template.get("slots", [])
        for si, slot in enumerate(slots):
            sr = pygame.Rect(px, y, w, 26)
            del_r = pygame.Rect(px + w - 50, y + 4, 40, 18)
            if del_r.collidepoint(mx, my):
                slots.pop(si)
                if self.selected_slot >= si:
                    self.selected_slot = max(-1, self.selected_slot - 1)
                return True
            if sr.collidepoint(mx, my):
                self.selected_slot = si
                return True
            y += 30

        return True

    def _handle_new_dialog_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                name = self._new_name_field.value.strip()
                if name:
                    self.template_name = name
                    self.template = {
                        "name": name,
                        "width": self.state.map_w or 20,
                        "height": self.state.map_h or 15,
                        "base_tiles": [],
                        "slots": [],
                        "fixed_entities": [],
                        "portals": [],
                    }
                    self.state.toast(f"Template '{name}' created")
                self._new_name_field = None
                self.ctx.release_focus()
                self._refresh_template_list()
                return True
            if event.key == pygame.K_ESCAPE:
                self._new_name_field = None
                self.ctx.release_focus()
                return True
        if self._new_name_field:
            self._new_name_field.handle_event(event)
        return True
