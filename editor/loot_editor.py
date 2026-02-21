"""editor/loot_editor.py — Visual loot table editor.

Full-screen overlay for creating and editing loot tables.  Shows all
tables, their pools, and pool entries with inline editing.

All positions are computed via ``Layout.s()`` so the overlay scales
correctly at any DPI / window size.  Draw and event handling share the
same pre-computed rects to prevent misalignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pygame

from editor.layout import Layout
from editor.ui import (
    Theme, UIContext, Button, TextField,
    draw_text, draw_text_centered,
)
from editor.state import (
    EditorState, load_loot_tables, save_loot_tables, load_item_ids,
)


# ── Rect cache for draw / event sharing ─────────────────────────

@dataclass
class _PoolLayout:
    """Cached geometry for one pool in the detail panel."""
    header: pygame.Rect
    delete_btn: pygame.Rect
    edit_btn: pygame.Rect
    col_header_y: int
    entries: list[pygame.Rect] = field(default_factory=list)
    entry_del: list[pygame.Rect] = field(default_factory=list)
    add_entry: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    divider_y: int = 0


class LootTableEditor:
    """Full-screen loot table editor overlay."""

    def __init__(self, state: EditorState, ctx: UIContext):
        self.state = state
        self.ctx = ctx
        self.active = False

        # Data
        self.tables: dict[str, Any] = {}
        self.item_ids: list[str] = []
        self.selected_table: str = ""
        self.scroll_left = 0
        self.scroll_right = 0

        # Buttons (positioned each frame in _compute)
        self.btn_close = Button(pygame.Rect(0, 0, 70, 28), "Close",
                                color=Theme.PANEL_LITE)
        self.btn_save = Button(pygame.Rect(0, 0, 70, 28), "Save",
                               color=(40, 80, 40),
                               text_color=Theme.SUCCESS)
        self.btn_new_table = Button(pygame.Rect(0, 0, 100, 28),
                                    "New Table",
                                    color=Theme.PANEL_LITE)
        self.btn_new_pool = Button(pygame.Rect(0, 0, 90, 28),
                                   "Add Pool",
                                   color=Theme.PANEL_LITE)

        # New table dialog
        self._new_table_field: TextField | None = None

        # Layout caches (rebuilt every frame in draw → _compute)
        self._list_rects: list[tuple[str, pygame.Rect]] = []
        self._del_table_rect = pygame.Rect(0, 0, 0, 0)
        self._pool_layouts: list[_PoolLayout] = []
        self._list_w: int = 220

    def open(self):
        self.active = True
        self.tables = load_loot_tables()
        self.item_ids = load_item_ids()
        if self.tables and not self.selected_table:
            self.selected_table = next(iter(self.tables))

    def close(self):
        self.active = False
        self.ctx.release_focus()

    # ── Scaled metrics ───────────────────────────────────────────

    @staticmethod
    def _s(v: int) -> int:
        return Layout.s(v)

    # ── Layout computation (shared by draw + events) ─────────────

    def _compute(self, sw: int, sh: int):
        """Compute ALL rects for this frame (list + detail)."""
        s = self._s
        pad = s(8)
        hdr_h = s(40)
        btn_h = s(28)
        btn_sm = s(24)
        row_h = s(28)
        row_gap = s(32)
        entry_h = s(22)
        entry_gap = s(24)
        pool_hdr_h = s(26)
        pad_lg = s(12)
        self._list_w = lw = min(s(220), sw // 3)

        # ── Left panel: table list rects ─────────────────────
        self._list_rects.clear()
        y = hdr_h + pad_lg + btn_h + pad
        for table_id in sorted(self.tables.keys()):
            iy = y - self.scroll_left
            self._list_rects.append(
                (table_id, pygame.Rect(pad, iy, lw - pad * 2, row_h)))
            y += row_gap
        self._del_table_rect = pygame.Rect(
            pad, sh - pad - row_h, lw - pad * 2, row_h)

        # ── Header buttons ───────────────────────────────────
        self.btn_close.rect = pygame.Rect(
            sw - pad * 10, pad - 2, s(70), btn_h)
        self.btn_save.rect = pygame.Rect(
            sw - pad * 20, pad - 2, s(70), btn_h)
        self.btn_new_table.rect = pygame.Rect(
            pad, hdr_h + pad_lg, lw - pad * 2, btn_h)

        # ── Right panel: detail rects ────────────────────────
        self._pool_layouts.clear()
        if not self.selected_table or self.selected_table not in self.tables:
            return
        table = self.tables[self.selected_table]
        pools = table.get("pools", [])

        px = lw + pad_lg
        w = sw - lw - pad_lg * 2
        desc_y = hdr_h + pad_lg
        pool_btn_y = desc_y + entry_gap * 2
        self.btn_new_pool.rect = pygame.Rect(px, pool_btn_y, s(100), btn_sm)

        y = pool_btn_y + btn_sm + pad_lg - self.scroll_right

        for pool in pools:
            pl = _PoolLayout(
                header=pygame.Rect(px, y, w, pool_hdr_h),
                delete_btn=pygame.Rect(
                    px + w - pad * 8, y + 2, pad * 7, entry_h - 2),
                edit_btn=pygame.Rect(
                    px + w - pad * 17, y + 2, pad * 8, entry_h - 2),
                col_header_y=y + pool_hdr_h + 2,
            )
            y += pool_hdr_h + 4
            y += entry_h - 4  # column header row

            for _ in pool.get("entries", []):
                pl.entries.append(
                    pygame.Rect(px + 4, y, w - pad, entry_h))
                pl.entry_del.append(
                    pygame.Rect(px + w - pad * 5, y + 1,
                                pad * 4, entry_h - 4))
                y += entry_gap

            pl.add_entry = pygame.Rect(
                px + pad, y, s(120), entry_h)
            y += row_gap
            pl.divider_y = y - pad
            y += pad_lg
            self._pool_layouts.append(pl)

    # ── Drawing ──────────────────────────────────────────────────

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
        draw_text(surface, "LOOT TABLE EDITOR",
                  s(16), s(10), Theme.ACCENT2, font)
        self.btn_close.draw(surface, font_sm)
        self.btn_save.draw(surface, font_sm)

        # Divider
        lw = self._list_w
        pygame.draw.line(surface, Theme.BORDER, (lw, hdr_h), (lw, sh))

        # Left panel
        self._draw_table_list(surface, font_sm, sh)

        # Right panel
        if self.selected_table and self.selected_table in self.tables:
            self._draw_table_detail(surface, font, font_sm, sw)
        else:
            draw_text(surface, "Select a table from the left panel",
                      lw + s(20), hdr_h + s(40), Theme.TEXT_DIM, font)

        # Dialog overlay
        if self._new_table_field is not None:
            self._draw_new_table_dialog(surface, font, font_sm, sw, sh, dt)

    def _draw_table_list(self, surface, font_sm, sh):
        s = self._s
        pad = s(8)
        br = max(2, Layout.border_r)

        self.btn_new_table.draw(surface, font_sm)

        mx, my = pygame.mouse.get_pos()
        for table_id, ir in self._list_rects:
            if ir.bottom < s(40) or ir.top > sh:
                continue
            is_sel = (table_id == self.selected_table)
            hov = ir.collidepoint(mx, my)
            if is_sel:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=br)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=br)
            color = Theme.ACCENT2 if is_sel else Theme.TEXT
            draw_text(surface, table_id, ir.x + pad, ir.y + pad - 2,
                      color, font_sm)
            pools = self.tables[table_id].get("pools", [])
            draw_text(surface, f"({len(pools)} pools)",
                      ir.right - s(70), ir.y + pad - 2,
                      Theme.TEXT_DIM, font_sm)

        if self.selected_table:
            dr = self._del_table_rect
            hov = dr.collidepoint(mx, my)
            bg = (100, 40, 40) if hov else (60, 30, 30)
            pygame.draw.rect(surface, bg, dr, border_radius=br)
            draw_text_centered(surface, "Delete Table", dr,
                               Theme.DANGER, font_sm)

    def _draw_table_detail(self, surface, font, font_sm, sw):
        s = self._s
        pad = s(8)
        br = max(2, Layout.border_r)
        table = self.tables[self.selected_table]
        lw = self._list_w
        px = lw + s(12)
        w = sw - lw - s(24)

        # Table header text
        desc_y = s(40) + s(12)
        draw_text(surface, f"Table: {self.selected_table}",
                  px, desc_y, Theme.ACCENT2, font)
        desc = table.get("description", "")
        draw_text(surface, f"Desc: {desc if desc else '(none)'}",
                  px, desc_y + s(24), Theme.TEXT_DIM, font_sm)
        self.btn_new_pool.draw(surface, font_sm)

        # Column layout
        item_col = px + pad + 2
        weight_col = px + s(160)
        min_col = px + s(230)
        max_col = px + s(280)

        pools = table.get("pools", [])
        mx, my = pygame.mouse.get_pos()

        for pi, (pool, pl) in enumerate(zip(pools, self._pool_layouts)):
            pool_name = pool.get("name", f"pool_{pi}")
            rolls = pool.get("rolls", 1)
            bonus = pool.get("bonus_rolls", 0)

            # Pool header
            pygame.draw.rect(surface, Theme.PANEL_LITE, pl.header,
                             border_radius=br)
            draw_text(surface,
                      f"Pool: {pool_name}  |  "
                      f"Rolls: {rolls}  Bonus: {bonus}",
                      pl.header.x + pad, pl.header.y + pad - 3,
                      Theme.ACCENT, font_sm)

            # Delete / Edit
            if pl.delete_btn.collidepoint(mx, my):
                pygame.draw.rect(surface, (80, 30, 30), pl.delete_btn,
                                 border_radius=br - 1)
            draw_text(surface, "Del",
                      pl.delete_btn.x + pad, pl.delete_btn.y + 3,
                      Theme.DANGER, font_sm)
            if pl.edit_btn.collidepoint(mx, my):
                pygame.draw.rect(surface, Theme.HIGHLIGHT, pl.edit_btn,
                                 border_radius=br - 1)
            draw_text(surface, "Edit",
                      pl.edit_btn.x + pad * 2, pl.edit_btn.y + 3,
                      Theme.TEXT_DIM, font_sm)

            # Column headers
            cy = pl.col_header_y
            draw_text(surface, "Item", item_col, cy, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Weight", weight_col, cy,
                      Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Min", min_col, cy, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Max", max_col, cy, Theme.TEXT_DIM, font_sm)

            entries = pool.get("entries", [])
            for ei, entry in enumerate(entries):
                if ei >= len(pl.entries):
                    break
                er = pl.entries[ei]
                if er.collidepoint(mx, my):
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, er,
                                     border_radius=br - 1)
                draw_text(surface, entry.get("item", "???")[:18],
                          er.x + pad, er.y + 3, Theme.TEXT, font_sm)
                draw_text(surface, str(entry.get("weight", 1)),
                          weight_col + pad, er.y + 3,
                          Theme.TEXT, font_sm)
                draw_text(surface, str(entry.get("min_count", 1)),
                          min_col + pad, er.y + 3, Theme.TEXT, font_sm)
                draw_text(surface, str(entry.get("max_count", 1)),
                          max_col + pad, er.y + 3, Theme.TEXT, font_sm)

                del_r = pl.entry_del[ei]
                if del_r.collidepoint(mx, my):
                    pygame.draw.rect(surface, (80, 30, 30), del_r,
                                     border_radius=br - 1)
                draw_text(surface, "X",
                          del_r.x + pad, del_r.y + 1,
                          Theme.DANGER, font_sm)

            # Add entry
            ar = pl.add_entry
            hov = ar.collidepoint(mx, my)
            bg = Theme.HIGHLIGHT if hov else Theme.PANEL
            pygame.draw.rect(surface, bg, ar, border_radius=br - 1)
            pygame.draw.rect(surface, Theme.BORDER, ar, 1,
                             border_radius=br - 1)
            draw_text(surface, "+ Add Entry",
                      ar.x + s(12), ar.y + 3, Theme.TEXT_DIM, font_sm)

            # Divider
            pygame.draw.line(surface, Theme.BORDER,
                             (px, pl.divider_y), (px + w, pl.divider_y), 1)

    def _draw_new_table_dialog(self, surface, font, font_sm, sw, sh, dt):
        s = self._s
        dw, dh = s(400), s(100)
        rect = pygame.Rect((sw - dw) // 2, (sh - dh) // 2, dw, dh)
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, Theme.ACCENT2, rect, 2, border_radius=10)
        draw_text(surface, "New Loot Table ID:",
                  rect.x + s(16), rect.y + s(14), Theme.TEXT_DIM, font_sm)
        self._new_table_field.rect = pygame.Rect(
            rect.x + s(16), rect.y + s(38), dw - s(32), s(28))
        self._new_table_field.draw(surface, font, dt)
        draw_text(surface, "Enter = create  |  Esc = cancel",
                  rect.x + s(16), rect.y + s(74), Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.active:
            return False

        # New table dialog consumes all events
        if self._new_table_field is not None:
            return self._handle_new_table_event(event)

        # Buttons
        if self.btn_close.handle_event(event):
            self.close()
            return True
        if self.btn_save.handle_event(event):
            if save_loot_tables(self.tables):
                self.state.toast("Loot tables saved!")
            else:
                self.state.toast("Failed to save loot tables")
            return True

        # Keyboard shortcuts
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True
            if event.key == pygame.K_s and event.mod & pygame.KMOD_CTRL:
                if save_loot_tables(self.tables):
                    self.state.toast("Loot tables saved!")
                return True

        # New table
        if self.btn_new_table.handle_event(event):
            self._new_table_field = TextField(
                pygame.Rect(0, 0, 368, 28), self.ctx, value="")
            self.ctx.take_focus(self._new_table_field.uid)
            return True

        # Scroll
        if event.type == pygame.MOUSEWHEEL:
            mx, _ = pygame.mouse.get_pos()
            if mx < self._list_w:
                self.scroll_left = max(0, self.scroll_left - event.y * 30)
            else:
                self.scroll_right = max(0, self.scroll_right - event.y * 30)
            return True

        # Mouse clicks — use cached rects (computed during draw)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # Delete table
            if (self.selected_table
                    and self._del_table_rect.collidepoint(mx, my)):
                if self.selected_table in self.tables:
                    del self.tables[self.selected_table]
                    self.selected_table = (
                        next(iter(self.tables)) if self.tables else "")
                    self.state.toast("Table deleted")
                return True

            # Table list selection
            for table_id, ir in self._list_rects:
                if ir.collidepoint(mx, my):
                    self.selected_table = table_id
                    self.scroll_right = 0
                    return True

            # Detail panel clicks
            return self._handle_detail_click(mx, my)

        return True

    def _handle_detail_click(self, mx: int, my: int) -> bool:
        """Handle clicks in the detail panel using pre-computed rects."""
        if not self.selected_table or self.selected_table not in self.tables:
            return True
        table = self.tables[self.selected_table]
        pools = table.get("pools", [])

        # Add pool button (already positioned by _compute)
        if self.btn_new_pool.rect.collidepoint(mx, my):
            pools_list = table.setdefault("pools", [])
            pools_list.append({
                "name": f"pool_{len(pools_list)}",
                "rolls": 1, "bonus_rolls": 0, "entries": [],
            })
            self.state.toast("Pool added")
            return True

        for pi, pl in enumerate(self._pool_layouts):
            if pi >= len(pools):
                break
            pool = pools[pi]

            # Delete pool
            if pl.delete_btn.collidepoint(mx, my):
                pools.pop(pi)
                self.state.toast("Pool deleted")
                return True

            entries = pool.get("entries", [])

            # Delete entry
            for ei, del_r in enumerate(pl.entry_del):
                if ei < len(entries) and del_r.collidepoint(mx, my):
                    entries.pop(ei)
                    self.state.toast("Entry removed")
                    return True

            # Click entry row → cycle item
            for ei, er in enumerate(pl.entries):
                if ei < len(entries) and er.collidepoint(mx, my):
                    if self.item_ids:
                        cur = entries[ei].get("item", "")
                        try:
                            idx = self.item_ids.index(cur)
                            idx = (idx + 1) % len(self.item_ids)
                        except ValueError:
                            idx = 0
                        entries[ei]["item"] = self.item_ids[idx]
                    return True

            # Add entry
            if pl.add_entry.collidepoint(mx, my):
                entries.append({
                    "item": self.item_ids[0] if self.item_ids else "unknown",
                    "weight": 1, "min_count": 1, "max_count": 1,
                })
                self.state.toast("Entry added")
                return True

        return True

    def _handle_new_table_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                tid = self._new_table_field.value.strip()
                if tid and tid not in self.tables:
                    self.tables[tid] = {"description": "", "pools": []}
                    self.selected_table = tid
                    self.state.toast(f"Created table: {tid}")
                self._new_table_field = None
                self.ctx.release_focus()
                return True
            if event.key == pygame.K_ESCAPE:
                self._new_table_field = None
                self.ctx.release_focus()
                return True
        if self._new_table_field:
            self._new_table_field.handle_event(event)
        return True
