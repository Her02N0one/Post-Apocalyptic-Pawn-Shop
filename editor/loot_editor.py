"""editor/loot_editor.py — Visual loot table editor.

Full-screen overlay for creating set and editing loot tables.  Shows all
tables, their pools, and pool entries with inline editing.
"""

from __future__ import annotations

from typing import Any

import pygame

from editor.ui import (
    Theme, UIContext, Button, TextField,
    draw_text,
)
from editor.state import (
    EditorState, load_loot_tables, save_loot_tables, load_item_ids,
)


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

        # Buttons
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
        self.btn_new_entry = Button(pygame.Rect(0, 0, 100, 28),
                                    "Add Entry",
                                    color=Theme.PANEL_LITE)

        # Inline editing
        self._editing_field: TextField | None = None
        self._editing_target: tuple | None = None  # (table, pool_idx, entry_idx, field)

        # New table dialog
        self._new_table_field: TextField | None = None

    def open(self):
        self.active = True
        self.tables = load_loot_tables()
        self.item_ids = load_item_ids()
        if self.tables and not self.selected_table:
            self.selected_table = next(iter(self.tables))

    def close(self):
        self.active = False
        self.ctx.release_focus()

    # ── Drawing ──────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             font_sm: pygame.font.Font, dt: float = 0.016):
        if not self.active:
            return

        sw, sh = surface.get_size()
        surface.fill(Theme.BG)

        # Header bar
        pygame.draw.rect(surface, Theme.PANEL, (0, 0, sw, 40))
        pygame.draw.line(surface, Theme.BORDER, (0, 39), (sw, 39))
        draw_text(surface, "LOOT TABLE EDITOR", 16, 10, Theme.ACCENT2, font)

        self.btn_close.rect = pygame.Rect(sw - 80, 6, 70, 28)
        self.btn_close.draw(surface, font_sm)
        self.btn_save.rect = pygame.Rect(sw - 158, 6, 70, 28)
        self.btn_save.draw(surface, font_sm)

        # Split: table list (left 220px) | detail (right)
        list_w = 220
        pygame.draw.line(surface, Theme.BORDER, (list_w, 40), (list_w, sh))

        # ── Left: Table list ─────────────────────────────────
        self._draw_table_list(surface, font, font_sm, list_w, sh)

        # ── Right: Table detail ──────────────────────────────
        if self.selected_table and self.selected_table in self.tables:
            self._draw_table_detail(surface, font, font_sm,
                                    list_w, sw, sh)
        else:
            draw_text(surface, "Select a table from the left panel",
                      list_w + 20, 80, Theme.TEXT_DIM, font)

        # New table dialog
        if self._new_table_field is not None:
            self._draw_new_table_dialog(surface, font, font_sm, dt)

    def _draw_table_list(self, surface, font, font_sm, list_w, sh):
        # New table button
        self.btn_new_table.rect = pygame.Rect(8, 50, list_w - 16, 28)
        self.btn_new_table.draw(surface, font_sm)

        y = 90
        mx, my = pygame.mouse.get_pos()
        for table_id in sorted(self.tables.keys()):
            iy = y - self.scroll_left
            if iy > sh:
                break
            if iy + 30 < 80:
                y += 32
                continue
            ir = pygame.Rect(6, iy, list_w - 12, 28)
            is_selected = (table_id == self.selected_table)
            hov = ir.collidepoint(mx, my)
            if is_selected:
                pygame.draw.rect(surface, Theme.SELECTED, ir,
                                 border_radius=4)
            elif hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir,
                                 border_radius=4)
            color = Theme.ACCENT2 if is_selected else Theme.TEXT
            draw_text(surface, table_id, ir.x + 8, ir.y + 6,
                      color, font_sm)
            # Pool count
            pools = self.tables[table_id].get("pools", [])
            draw_text(surface, f"({len(pools)} pools)",
                      ir.right - 70, ir.y + 6, Theme.TEXT_DIM, font_sm)
            y += 32

        # Delete table button at bottom
        if self.selected_table:
            del_r = pygame.Rect(6, sh - 36, list_w - 12, 28)
            hov = del_r.collidepoint(mx, my)
            bg = (100, 40, 40) if hov else (60, 30, 30)
            pygame.draw.rect(surface, bg, del_r, border_radius=4)
            draw_text(surface, "Delete Table", del_r.x + 40, del_r.y + 6,
                      Theme.DANGER, font_sm)

    def _draw_table_detail(self, surface, font, font_sm, lx, sw, sh):
        table = self.tables[self.selected_table]
        px = lx + 12
        w = sw - lx - 24

        # Table header
        draw_text(surface, f"Table: {self.selected_table}",
                  px, 50, Theme.ACCENT2, font)
        desc = table.get("description", "")
        draw_text(surface, f"Desc: {desc if desc else '(none)'}",
                  px, 70, Theme.TEXT_DIM, font_sm)

        # Add pool button
        self.btn_new_pool.rect = pygame.Rect(px, 92, 100, 24)
        self.btn_new_pool.draw(surface, font_sm)

        y = 126 - self.scroll_right
        pools = table.get("pools", [])
        mx, my = pygame.mouse.get_pos()

        for pi, pool in enumerate(pools):
            pool_name = pool.get("name", f"pool_{pi}")
            rolls = pool.get("rolls", 1)
            bonus = pool.get("bonus_rolls", 0)

            # Pool header
            pool_rect = pygame.Rect(px, y, w, 26)
            pygame.draw.rect(surface, Theme.PANEL_LITE, pool_rect,
                             border_radius=4)
            draw_text(surface, f"Pool: {pool_name}  |  "
                      f"Rolls: {rolls}  Bonus: {bonus}",
                      px + 8, y + 5, Theme.ACCENT, font_sm)

            # Delete pool button
            del_pool_r = pygame.Rect(px + w - 60, y + 2, 52, 20)
            if del_pool_r.collidepoint(mx, my):
                pygame.draw.rect(surface, (80, 30, 30), del_pool_r,
                                 border_radius=3)
            draw_text(surface, "Del", del_pool_r.x + 12, del_pool_r.y + 3,
                      Theme.DANGER, font_sm)

            # Edit rolls button
            edit_r = pygame.Rect(px + w - 130, y + 2, 60, 20)
            if edit_r.collidepoint(mx, my):
                pygame.draw.rect(surface, Theme.HIGHLIGHT, edit_r,
                                 border_radius=3)
            draw_text(surface, "Edit", edit_r.x + 16, edit_r.y + 3,
                      Theme.TEXT_DIM, font_sm)

            y += 30

            # Entries
            entries = pool.get("entries", [])
            # Header row
            draw_text(surface, "Item", px + 10, y, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Weight", px + 160, y, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Min", px + 230, y, Theme.TEXT_DIM, font_sm)
            draw_text(surface, "Max", px + 280, y, Theme.TEXT_DIM, font_sm)
            y += 18

            for ei, entry in enumerate(entries):
                item = entry.get("item", "???")
                weight = entry.get("weight", 1)
                min_c = entry.get("min_count", 1)
                max_c = entry.get("max_count", 1)

                er = pygame.Rect(px + 4, y, w - 8, 22)
                if er.collidepoint(mx, my):
                    pygame.draw.rect(surface, Theme.HIGHLIGHT, er,
                                     border_radius=3)

                draw_text(surface, item[:18], px + 10, y + 3,
                          Theme.TEXT, font_sm)
                draw_text(surface, str(weight), px + 168, y + 3,
                          Theme.TEXT, font_sm)
                draw_text(surface, str(min_c), px + 236, y + 3,
                          Theme.TEXT, font_sm)
                draw_text(surface, str(max_c), px + 286, y + 3,
                          Theme.TEXT, font_sm)

                # Delete entry
                del_r = pygame.Rect(px + w - 40, y + 1, 32, 18)
                if del_r.collidepoint(mx, my):
                    pygame.draw.rect(surface, (80, 30, 30), del_r,
                                     border_radius=2)
                draw_text(surface, "X", del_r.x + 10, del_r.y + 1,
                          Theme.DANGER, font_sm)

                y += 24

            # Add entry button
            add_r = pygame.Rect(px + 10, y, 100, 22)
            self.btn_new_entry.rect = add_r
            hov = add_r.collidepoint(mx, my)
            bg = Theme.HIGHLIGHT if hov else Theme.PANEL
            pygame.draw.rect(surface, bg, add_r, border_radius=3)
            pygame.draw.rect(surface, Theme.BORDER, add_r, 1,
                             border_radius=3)
            draw_text(surface, "+ Add Entry", add_r.x + 12, add_r.y + 3,
                      Theme.TEXT_DIM, font_sm)
            y += 32
            # Pool divider
            pygame.draw.line(surface, Theme.BORDER,
                             (px, y), (px + w, y), 1)
            y += 12

    def _draw_new_table_dialog(self, surface, font, font_sm, dt):
        sw, sh = surface.get_size()
        rect = pygame.Rect((sw - 400) // 2, (sh - 100) // 2, 400, 100)
        pygame.draw.rect(surface, Theme.PANEL, rect, border_radius=10)
        pygame.draw.rect(surface, Theme.ACCENT2, rect, 2, border_radius=10)
        draw_text(surface, "New Loot Table ID:", rect.x + 16, rect.y + 14,
                  Theme.TEXT_DIM, font_sm)
        self._new_table_field.rect = pygame.Rect(
            rect.x + 16, rect.y + 38, 368, 28)
        self._new_table_field.draw(surface, font, dt)
        draw_text(surface, "Enter = create  |  Esc = cancel",
                  rect.x + 16, rect.y + 74, Theme.TEXT_DIM, font_sm)

    # ── Event handling ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.active:
            return False

        # New table dialog
        if self._new_table_field is not None:
            return self._handle_new_table_event(event)

        # Close button
        if self.btn_close.handle_event(event):
            self.close()
            return True

        # Save button
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
                pygame.Rect(0, 0, 368, 28), self.ctx,
                value="", placeholder="my_loot_table")
            self.ctx.take_focus(self._new_table_field.uid)
            return True

        # Scroll
        if event.type == pygame.MOUSEWHEEL:
            mx, _ = pygame.mouse.get_pos()
            if mx < 220:
                self.scroll_left = max(0, self.scroll_left - event.y * 30)
            else:
                self.scroll_right = max(0, self.scroll_right - event.y * 30)
            return True

        # Table list click
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            sw, sh = pygame.display.get_surface().get_size()

            # Delete table button
            if self.selected_table and mx < 220:
                del_r = pygame.Rect(6, sh - 36, 208, 28)
                if del_r.collidepoint(mx, my):
                    if self.selected_table in self.tables:
                        del self.tables[self.selected_table]
                        self.selected_table = (
                            next(iter(self.tables)) if self.tables else "")
                        self.state.toast("Table deleted")
                    return True

            # Table selection
            if mx < 220:
                y = 90
                for table_id in sorted(self.tables.keys()):
                    iy = y - self.scroll_left
                    ir = pygame.Rect(6, iy, 208, 28)
                    if ir.collidepoint(mx, my):
                        self.selected_table = table_id
                        self.scroll_right = 0
                        return True
                    y += 32
                return True

            # Detail panel clicks
            if self.selected_table and self.selected_table in self.tables:
                return self._handle_detail_click(event, mx, my)

        return True

    def _handle_detail_click(self, event, mx, my) -> bool:
        table = self.tables[self.selected_table]
        sw = pygame.display.get_surface().get_width()
        px = 232
        w = sw - 244

        # Add pool
        if self.btn_new_pool.handle_event(event):
            pools = table.setdefault("pools", [])
            pools.append({
                "name": f"pool_{len(pools)}",
                "rolls": 1, "bonus_rolls": 0, "entries": [],
            })
            self.state.toast("Pool added")
            return True

        # Walk pools for clicks
        y = 126 - self.scroll_right
        pools = table.get("pools", [])

        for pi, pool in enumerate(pools):
            # Delete pool
            del_pool_r = pygame.Rect(px + w - 60, y + 2, 52, 20)
            if del_pool_r.collidepoint(mx, my):
                pools.pop(pi)
                self.state.toast("Pool deleted")
                return True

            y += 30

            # Skip header
            y += 18

            entries = pool.get("entries", [])
            for ei, entry in enumerate(entries):
                # Delete entry
                del_r = pygame.Rect(px + w - 40, y + 1, 32, 18)
                if del_r.collidepoint(mx, my):
                    entries.pop(ei)
                    self.state.toast("Entry removed")
                    return True

                # Click on entry row → cycle item
                er = pygame.Rect(px + 4, y, w - 48, 22)
                if er.collidepoint(mx, my):
                    # Cycle to next item
                    if self.item_ids:
                        cur = entry.get("item", "")
                        try:
                            idx = self.item_ids.index(cur)
                            idx = (idx + 1) % len(self.item_ids)
                        except ValueError:
                            idx = 0
                        entry["item"] = self.item_ids[idx]
                    return True

                y += 24

            # Add entry
            add_r = pygame.Rect(px + 10, y, 100, 22)
            if add_r.collidepoint(mx, my):
                entries.append({
                    "item": self.item_ids[0] if self.item_ids else "unknown",
                    "weight": 1, "min_count": 1, "max_count": 1,
                })
                self.state.toast("Entry added")
                return True

            y += 44

        return True

    def _handle_new_table_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                tid = self._new_table_field.value.strip()
                if tid and tid not in self.tables:
                    self.tables[tid] = {
                        "description": "", "pools": [],
                    }
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
