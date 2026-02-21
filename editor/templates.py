"""editor/templates.py — Zone template system.

Allows creation of zone *templates* with rectangular *slots* that can be
filled with different *room* variants at bake-time.  This gives variety
(e.g.  apartment complexes where every unit differs) while keeping a
consistent overall layout.

All overlay positions are computed via ``Layout.s()`` so the overlay
scales correctly at any DPI / window size.  Draw and event handling
share the same pre-computed rects.

Data model
----------
**Template** (``templates/<name>.json``)::

    {
        "name": "apartment_block",
        "width": 50, "height": 40,
        "base_tiles": [[int, ...]],
        "slots": [ { "name": ..., "x": ..., ... } ],
        "fixed_entities": [ {...}, ... ],
        "portals": [ {...}, ... ]
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
from dataclasses import dataclass, field
from typing import Any

import pygame

from editor.layout import Layout
from editor.state import EditorState, TEMPLATES_DIR, ROOMS_DIR
from editor.ui import (
    Theme, UIContext, Button, TextField,
    draw_text, draw_text_centered,
)


# ═════════════════════════════════════════════════════════════════
# I/O helpers
# ═════════════════════════════════════════════════════════════════

def list_templates() -> list[str]:
    if not os.path.isdir(TEMPLATES_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(TEMPLATES_DIR) if f.endswith(".json"))


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
    if not os.path.isdir(ROOMS_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(ROOMS_DIR) if f.endswith(".json"))


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


# ═════════════════════════════════════════════════════════════════
# Baking
# ═════════════════════════════════════════════════════════════════

def bake_template(template: dict[str, Any],
                  seed: int | None = None) -> dict[str, Any]:
    """Convert a template into a concrete zone dict.

    For each slot the baking process:
    1. Gathers all rooms whose tags intersect the slot's tags.
    2. Filters by size (must be <= slot size).
    3. Picks one at random (using *seed* for reproducibility).
    4. Pastes the room's tiles into the base grid (centered in slot).
    5. Appends the room's entities with offset positions.
    """
    rng = random.Random(seed)
    w = template["width"]
    h = template["height"]

    base = template.get("base_tiles")
    tiles = [row[:] for row in base] if base else [[0] * w for _ in range(h)]
    entities = deepcopy(template.get("fixed_entities", []))
    portals = deepcopy(template.get("portals", []))
    anchor = template.get("anchor", [w // 2, h // 2])

    room_cache: dict[str, dict] = {}
    for rn in list_rooms():
        rd = load_room(rn)
        if rd:
            room_cache[rn] = rd

    for slot in template.get("slots", []):
        sx, sy, sw_, sh_ = slot["x"], slot["y"], slot["w"], slot["h"]
        slot_tags = set(slot.get("tags", []))
        required = slot.get("required", True)

        candidates = []
        for rn, rd in room_cache.items():
            room_tags = set(rd.get("tags", []))
            rw, rh = rd.get("width", 0), rd.get("height", 0)
            if rw > sw_ or rh > sh_:
                continue
            if slot_tags and room_tags and not (slot_tags & room_tags):
                continue
            candidates.append((rn, rd))

        if not candidates:
            if required:
                for row in range(sy, min(sy + sh_, h)):
                    for col in range(sx, min(sx + sw_, w)):
                        tiles[row][col] = 1
            continue

        rn, rd = rng.choice(candidates)
        rw = rd.get("width", sw_)
        rh = rd.get("height", sh_)
        ox = sx + (sw_ - rw) // 2
        oy = sy + (sh_ - rh) // 2

        for ry, row in enumerate(rd.get("tiles", [])):
            ty = oy + ry
            if 0 <= ty < h:
                for rx, tile_id in enumerate(row):
                    tx = ox + rx
                    if 0 <= tx < w:
                        tiles[ty][tx] = tile_id

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
        "width": w, "height": h,
        "anchor": anchor, "tiles": tiles,
        "entities": entities, "portals": portals,
        "first_person": template.get("first_person", False),
    }


# ═════════════════════════════════════════════════════════════════
# Rect cache for draw / event sharing
# ═════════════════════════════════════════════════════════════════

@dataclass
class _SlotLayout:
    """Cached geometry for one slot row in the detail panel."""
    row: pygame.Rect
    delete_btn: pygame.Rect


# ═════════════════════════════════════════════════════════════════
# Template Editor
# ═════════════════════════════════════════════════════════════════

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

        # Buttons (positioned per frame in _compute)
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
        self._tag_field: TextField | None = None

        # Layout caches
        self._template_names: list[str] = []
        self._list_rects: list[tuple[str, pygame.Rect]] = []
        self._room_rects: list[tuple[str, pygame.Rect]] = []
        self._new_btn_rect = pygame.Rect(0, 0, 0, 0)
        self._slot_layouts: list[_SlotLayout] = []
        self._list_w: int = 200
        self._preview_rect = pygame.Rect(0, 0, 0, 0)

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
        s = self.state
        return {
            "name": s.zone_name or "untitled",
            "width": s.map_w, "height": s.map_h,
            "base_tiles": [row[:] for row in s.tiles],
            "slots": [],
            "fixed_entities": [e.to_dict() for e in s.entities],
            "portals": deepcopy(s.portals),
            "first_person": s.first_person,
        }

    # ── Export selection as room ──────────────────────────────

    def export_room_from_selection(self, name: str, x: int, y: int,
                                   w: int, h: int,
                                   tags: list[str]) -> bool:
        s = self.state
        tiles = []
        for row in range(y, min(y + h, s.map_h)):
            r = []
            for col in range(x, min(x + w, s.map_w)):
                r.append(s.tiles[row][col])
            tiles.append(r)
        ents = []
        for e in s.entities:
            if e.position is None:
                continue
            ex, ey = e.position.x, e.position.y
            if x <= ex < x + w and y <= ey < y + h:
                ec = e.copy()
                ec.position.x -= x
                ec.position.y -= y
                ents.append(ec.to_dict())
        room = {
            "name": name, "tags": tags,
            "width": w, "height": h,
            "tiles": tiles, "entities": ents,
        }
        return save_room(name, room)

    # ── Scaled helper ────────────────────────────────────────

    @staticmethod
    def _s(v: int) -> int:
        return Layout.s(v)

    # ── Layout computation (shared by draw + events) ─────────

    def _compute(self, sw: int, sh: int):
        s = self._s
        pad = s(8)
        pad_lg = s(12)
        hdr_h = s(40)
        btn_h = s(28)
        btn_sm = s(24)
        row_h = s(26)
        row_gap = s(30)
        self._list_w = lw = min(s(200), sw // 3)

        # ── Header buttons ───────────────────────────────────
        self.btn_close.rect = pygame.Rect(
            sw - pad * 10, pad - 2, s(70), btn_h)
        self.btn_save.rect = pygame.Rect(
            sw - pad * 20, pad - 2, s(70), btn_h)
        self.btn_bake.rect = pygame.Rect(
            sw - pad * 35, pad - 2, s(110), btn_h)

        # ── Left panel: list rects ───────────────────────────
        self._list_rects.clear()
        self._room_rects.clear()
        self._new_btn_rect = pygame.Rect(pad, hdr_h + pad_lg,
                                         lw - pad * 2, row_h)

        y = hdr_h + pad_lg + row_h + pad
        for tn in self._template_names:
            self._list_rects.append(
                (tn, pygame.Rect(pad, y, lw - pad * 2, row_h)))
            y += row_gap

        # Room variants section
        y += s(20)
        room_label_y = y + pad
        y = room_label_y + s(22)
        rooms = list_rooms()
        for rn in rooms:
            self._room_rects.append(
                (rn, pygame.Rect(pad, y, lw - pad * 2, s(22))))
            y += s(24)

        # ── Right panel: detail rects ────────────────────────
        self._slot_layouts.clear()
        if self.template is None:
            # Position "From Current Zone" button even when no template
            self.btn_from_zone.rect = pygame.Rect(
                lw + s(20), hdr_h + s(50), s(160), btn_h)
            return

        t = self.template
        px = lw + pad_lg
        w = sw - lw - pad_lg * 2

        desc_y = hdr_h + pad_lg
        btns_y = desc_y + s(24) * 2
        self.btn_new_slot.rect = pygame.Rect(px, btns_y, s(100), btn_sm)
        self.btn_export_room.rect = pygame.Rect(
            px + s(112), btns_y, s(120), btn_sm)
        self.btn_from_zone.rect = pygame.Rect(
            px + s(244), btns_y, s(160), btn_sm)

        y = btns_y + btn_sm + pad_lg - self.scroll
        slots = t.get("slots", [])
        for slot in slots:
            sr = pygame.Rect(px, y, w, row_h)
            del_r = pygame.Rect(px + w - s(50), y + 4, s(40), s(18))
            self._slot_layouts.append(_SlotLayout(row=sr, delete_btn=del_r))
            y += row_gap

        # Preview rect
        y += s(10)
        preview_h = min(s(200), sh - y - s(30))
        if preview_h > s(30):
            self._preview_rect = pygame.Rect(px + 2, y + 2,
                                             w - 4, preview_h - 4)
        else:
            self._preview_rect = pygame.Rect(0, 0, 0, 0)

    # ── Drawing ──────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if not self.active:
            return

        sw, sh = surface.get_size()
        s = self._s
        self._compute(sw, sh)
        surface.fill(Theme.BG)

        # Header bar
        hdr_h = s(40)
        pygame.draw.rect(surface, Theme.PANEL, (0, 0, sw, hdr_h))
        pygame.draw.line(surface, Theme.BORDER,
                         (0, hdr_h - 1), (sw, hdr_h - 1))
        draw_text(surface, "ZONE TEMPLATE EDITOR",
                  s(16), s(10), Theme.ACCENT2, font)
        self.btn_close.draw(surface, font_sm)
        self.btn_save.draw(surface, font_sm)
        self.btn_bake.draw(surface, font_sm)

        # Divider
        lw = self._list_w
        pygame.draw.line(surface, Theme.BORDER, (lw, hdr_h), (lw, sh))

        # Left panel
        self._draw_template_list(surface, font_sm, sh)

        # Right panel
        if self.template is not None:
            self._draw_template_detail(surface, font, font_sm, sw, sh)
        else:
            draw_text(surface, "No template loaded.",
                      lw + s(20), hdr_h + s(20),
                      Theme.TEXT_DIM, font)
            self.btn_from_zone.draw(surface, font_sm)

        # Dialog
        if self._new_name_field is not None:
            self._draw_new_dialog(surface, font, font_sm, sw, sh, dt)

    def _draw_template_list(self, surface, font_sm, sh):
        s = self._s
        pad = s(8)
        br = max(2, Layout.border_r)
        lw = self._list_w
        mx, my = pygame.mouse.get_pos()

        # New template button
        nr = self._new_btn_rect
        hov = nr.collidepoint(mx, my)
        bg = Theme.HIGHLIGHT if hov else Theme.PANEL_LITE
        pygame.draw.rect(surface, bg, nr, border_radius=br)
        draw_text(surface, "+ New Template",
                  nr.x + s(22), nr.y + pad - 3, Theme.ACCENT, font_sm)

        for tn, ir in self._list_rects:
            if ir.bottom < s(40) or ir.top > sh:
                continue
            is_sel = (tn == self.template_name)
            hov = ir.collidepoint(mx, my)
            if is_sel:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=br)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=br)
            draw_text(surface, tn, ir.x + pad, ir.y + pad - 3,
                      Theme.ACCENT2 if is_sel else Theme.TEXT, font_sm)

        # Room variants section
        if self._room_rects:
            first_room_y = self._room_rects[0][1].y
            sep_y = first_room_y - s(30)
            pygame.draw.line(surface, Theme.BORDER,
                             (pad, sep_y), (lw - pad, sep_y))
            draw_text(surface, "Room Variants:", pad,
                      sep_y + pad, Theme.ACCENT, font_sm)

        for rn, ir in self._room_rects:
            hov = ir.collidepoint(mx, my)
            if hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=br - 1)
            draw_text(surface, f"  {rn}", ir.x, ir.y + 3,
                      Theme.TEXT_DIM, font_sm)

    def _draw_template_detail(self, surface, font, font_sm, sw, sh):
        s = self._s
        pad = s(8)
        br = max(2, Layout.border_r)
        t = self.template
        lw = self._list_w
        px = lw + s(12)
        w = sw - lw - s(24)

        # Template header
        desc_y = s(40) + s(12)
        draw_text(surface, f"Template: {self.template_name}",
                  px, desc_y, Theme.ACCENT2, font)
        draw_text(surface,
                  f"Size: {t['width']} x {t['height']}  |  "
                  f"Slots: {len(t.get('slots', []))}  |  "
                  f"Entities: {len(t.get('fixed_entities', []))}",
                  px, desc_y + s(24), Theme.TEXT_DIM, font_sm)

        self.btn_new_slot.draw(surface, font_sm)
        self.btn_export_room.draw(surface, font_sm)
        self.btn_from_zone.draw(surface, font_sm)

        slots = t.get("slots", [])
        mx, my = pygame.mouse.get_pos()

        for si, (slot, sl) in enumerate(zip(slots, self._slot_layouts)):
            is_sel = (si == self.selected_slot)
            bg = Theme.SELECTED if is_sel else Theme.PANEL_LITE
            pygame.draw.rect(surface, bg, sl.row, border_radius=br)

            sn = slot.get("name", f"slot_{si}")
            tags = ", ".join(slot.get("tags", []))
            draw_text(surface,
                      f"{sn}  ({slot['w']}x{slot['h']})  "
                      f"@ ({slot['x']},{slot['y']})  "
                      f"tags: [{tags}]",
                      sl.row.x + pad, sl.row.y + pad - 3,
                      Theme.TEXT, font_sm)

            if sl.delete_btn.collidepoint(mx, my):
                pygame.draw.rect(surface, (80, 30, 30), sl.delete_btn,
                                 border_radius=br - 1)
            draw_text(surface, "Del",
                      sl.delete_btn.x + pad, sl.delete_btn.y + 1,
                      Theme.DANGER, font_sm)

        # Mini preview of base tiles
        pr = self._preview_rect
        if pr.w > 0:
            tw = max(t.get("width", 1), 1)
            th = max(t.get("height", 1), 1)
            scale = min(pr.w / tw, pr.h / th, 8)
            ox, oy = pr.x, pr.y
            base = t.get("base_tiles", [])
            for ry, row in enumerate(base):
                for rx, tid in enumerate(row):
                    if tid != "void":
                        c = (60, 50, 40) if tid == 1 else (50, 60, 50)
                        pygame.draw.rect(surface, c,
                                         (int(ox + rx * scale),
                                          int(oy + ry * scale),
                                          max(int(scale), 1),
                                          max(int(scale), 1)))
            for si, slot in enumerate(slots):
                ssx = int(ox + slot["x"] * scale)
                ssy = int(oy + slot["y"] * scale)
                ssw = int(slot["w"] * scale)
                ssh = int(slot["h"] * scale)
                is_sel = (si == self.selected_slot)
                color = Theme.ACCENT2 if is_sel else Theme.ACCENT
                pygame.draw.rect(surface, color,
                                 (ssx, ssy, ssw, ssh), 2)

    def _draw_new_dialog(self, surface, font, font_sm, sw, sh, dt):
        s = self._s
        dw, dh = s(400), s(100)
        rect = pygame.Rect((sw - dw) // 2, (sh - dh) // 2, dw, dh)
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, Theme.ACCENT2, rect, 2, border_radius=10)
        draw_text(surface, "Template name:",
                  rect.x + s(16), rect.y + s(14), Theme.TEXT_DIM, font_sm)
        self._new_name_field.rect = pygame.Rect(
            rect.x + s(16), rect.y + s(38), dw - s(32), s(28))
        self._new_name_field.draw(surface, font, dt)
        draw_text(surface, "Enter = create  |  Esc = cancel",
                  rect.x + s(16), rect.y + s(74), Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.active:
            return False

        # Dialog consumes all
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

            # From current zone
            if self.btn_from_zone.handle_event(event):
                self.template = self.from_current_zone()
                self.template_name = self.state.zone_name or "untitled"
                self.state.toast("Template created from zone")
                return True

            # New template
            if self._new_btn_rect.collidepoint(mx, my):
                self._new_name_field = TextField(
                    pygame.Rect(0, 0, 368, 28), self.ctx, value="")
                self.ctx.take_focus(self._new_name_field.uid)
                return True

            # Template list
            for tn, ir in self._list_rects:
                if ir.collidepoint(mx, my):
                    self.template_name = tn
                    self.template = load_template(tn)
                    self.selected_slot = -1
                    return True

            # Detail clicks — using cached rects
            if self.template:
                return self._handle_detail_click(mx, my)

        return True

    def _handle_detail_click(self, mx: int, my: int) -> bool:
        """Handle clicks in the detail panel using pre-computed rects."""
        t = self.template
        slots = t.get("slots", [])

        # New slot
        if self.btn_new_slot.rect.collidepoint(mx, my):
            slot_list = t.setdefault("slots", [])
            idx = len(slot_list)
            slot_list.append({
                "name": f"slot_{idx}",
                "x": 2, "y": 2, "w": 6, "h": 6,
                "tags": [], "required": True,
            })
            self.state.toast("Slot added")
            return True

        # Export room
        if self.btn_export_room.rect.collidepoint(mx, my):
            if self.selected_slot >= 0:
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
        for si, sl in enumerate(self._slot_layouts):
            if si >= len(slots):
                break
            if sl.delete_btn.collidepoint(mx, my):
                slots.pop(si)
                if self.selected_slot >= si:
                    self.selected_slot = max(-1, self.selected_slot - 1)
                return True
            if sl.row.collidepoint(mx, my):
                self.selected_slot = si
                return True

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
                        "base_tiles": [], "slots": [],
                        "fixed_entities": [], "portals": [],
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
