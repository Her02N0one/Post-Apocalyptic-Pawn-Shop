"""ui/inventory_modal.py — Player inventory modal.

Single-panel overlay for browsing items, using consumables, and
dropping items to the ground.  Drop emits a callback so the scene
can spawn a ground entity.
"""

from __future__ import annotations

import pygame
from typing import TYPE_CHECKING, Callable

from ui.modal import Modal
from ui.commands import CloseModal, HealPlayer, UICommand
from ui.helpers import sorted_items, draw_overlay, draw_title_bar, draw_item_row, ROW_H

if TYPE_CHECKING:
    from core.app import App
    from systems.item_registry import ItemRegistry


class InventoryModal(Modal):
    """Full-screen inventory overlay (player bag)."""

    def __init__(
        self,
        player_inv: dict[str, int],
        registry: "ItemRegistry | None" = None,
        title: str = "Inventory",
        on_drop: Callable[[str, int], None] | None = None,
    ) -> None:
        self.player_inv = player_inv
        self.registry = registry
        self.title = title
        self.on_drop = on_drop   # callback(item_id, qty) — scene spawns ground item

        # UI state
        self.cursor: int = 0
        self.message: str = ""
        self.message_timer: float = 0.0
        self._item_rects: list[tuple[pygame.Rect, int]] = []
        self._hover_idx: int = -1

    # ── helpers ───────────────────────────────────────────────────

    def _display_name(self, item_id: str) -> str:
        if self.registry:
            return self.registry.display_name(item_id)
        return item_id

    def _sprite_info(self, item_id: str) -> tuple[str, tuple[int, int, int]]:
        if self.registry:
            return self.registry.sprite_info(item_id)
        return "?", (200, 200, 200)

    def _item_type(self, item_id: str) -> str:
        if self.registry:
            return self.registry.item_type(item_id)
        return "misc"

    def _items(self) -> list[tuple[str, int]]:
        return sorted_items(self.player_inv)

    def _clamp_cursor(self) -> None:
        items = self._items()
        if self.cursor >= len(items):
            self.cursor = max(0, len(items) - 1)

    def _flash(self, msg: str) -> None:
        self.message = msg
        self.message_timer = 1.5

    # ── Modal interface ──────────────────────────────────────────

    def update(self, dt: float) -> None:
        if self.message_timer > 0:
            self.message_timer -= dt

    def handle_event(self, event: pygame.event.Event) -> list[UICommand]:
        cmds: list[UICommand] = []

        if event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(event)
            return cmds
        if event.type == pygame.MOUSEBUTTONDOWN:
            return self._handle_mouse_click(event)

        if event.type != pygame.KEYDOWN:
            return cmds

        key = event.key
        items = self._items()

        if key in (pygame.K_w, pygame.K_UP):
            self.cursor = max(0, self.cursor - 1)
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.cursor = min(len(items) - 1, self.cursor + 1) if items else 0
        elif key in (pygame.K_ESCAPE, pygame.K_i):
            cmds.append(CloseModal())
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if items:
                item_id, _qty = items[min(self.cursor, len(items) - 1)]
                cmds.extend(self._use_item(item_id))
                self._clamp_cursor()
        elif key == pygame.K_q:
            if items:
                item_id, _qty = items[min(self.cursor, len(items) - 1)]
                self._drop_single(item_id)
                self._clamp_cursor()
        elif key == pygame.K_x:
            if items:
                item_id, qty = items[min(self.cursor, len(items) - 1)]
                self._drop_stack(item_id, qty)
                self._clamp_cursor()

        return cmds

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        sw, sh = surface.get_size()
        self._item_rects.clear()
        draw_overlay(surface)

        modal_w = 440
        modal_h = min(sh - 60, 500)
        mx = (sw - modal_w) // 2
        my = (sh - modal_h) // 2

        pygame.draw.rect(surface, (35, 35, 55), (mx, my, modal_w, modal_h))
        pygame.draw.rect(surface, (140, 140, 180), (mx, my, modal_w, modal_h), 2)
        draw_title_bar(surface, app, mx, my, modal_w, self.title)

        y = my + 38

        # Item list
        items = self._items()
        if items:
            for idx, (item_id, qty) in enumerate(items):
                char, color = self._sprite_info(item_id)
                name = self._display_name(item_id)
                row = draw_item_row(
                    surface, app, mx + 4, y, modal_w - 8,
                    char=char, color=color, name=name, qty=qty,
                    selected=(idx == self.cursor),
                    hovered=(idx == self._hover_idx),
                )
                self._item_rects.append((row, idx))
                y += ROW_H
                if y > my + modal_h - 50:
                    app.draw_text(surface, "  ...", mx + 28, y,
                                  (150, 150, 150), font=app.font_sm)
                    break
        else:
            app.draw_text(surface, "  (empty)", mx + 14, y,
                          (120, 120, 140), font=app.font_sm)

        # Flash message
        if self.message and self.message_timer > 0:
            app.draw_text(surface, self.message, mx + 14, my + modal_h - 44,
                          (100, 255, 140), font=app.font_sm)

        # Controls
        app.draw_text(
            surface,
            "[Enter] Use  [Q] Drop  [X] Drop Stack  [I/Esc] Close",
            mx + 10, my + modal_h - 24, (100, 180, 100), font=app.font_sm,
        )

    # ── mouse ────────────────────────────────────────────────────

    def _handle_mouse_motion(self, event: pygame.event.Event) -> None:
        mx, my = event.pos
        self._hover_idx = -1
        for rect, idx in self._item_rects:
            if rect.collidepoint(mx, my):
                self._hover_idx = idx
                self.cursor = idx
                break

    def _handle_mouse_click(self, event: pygame.event.Event) -> list[UICommand]:
        cmds: list[UICommand] = []
        mx, my = event.pos
        mods = pygame.key.get_mods()

        for rect, idx in self._item_rects:
            if not rect.collidepoint(mx, my):
                continue
            self.cursor = idx
            items = self._items()
            if not items or idx >= len(items):
                return cmds
            item_id, qty = items[idx]

            if event.button == 1:
                if mods & pygame.KMOD_SHIFT:
                    self._drop_stack(item_id, qty)
                else:
                    cmds.extend(self._use_item(item_id))
                self._clamp_cursor()
            elif event.button == 3:
                self._drop_single(item_id)
                self._clamp_cursor()
            return cmds

        return cmds

    # ── actions ──────────────────────────────────────────────────

    def _use_item(self, item_id: str) -> list[UICommand]:
        cmds: list[UICommand] = []
        itype = self._item_type(item_id)

        if itype == "consumable":
            if self.player_inv.get(item_id, 0) <= 0:
                return cmds
            self.player_inv[item_id] -= 1
            if self.player_inv[item_id] <= 0:
                del self.player_inv[item_id]
            heal = 0.0
            if self.registry:
                heal = self.registry.get_field(item_id, "heal", 0.0)
            if heal > 0:
                cmds.append(HealPlayer(amount=heal))
            self._flash(f"Used {self._display_name(item_id)} (+{heal:.0f} HP)")
        else:
            self._flash(f"{self._display_name(item_id)}")

        return cmds

    def _drop_single(self, item_id: str) -> None:
        if self.player_inv.get(item_id, 0) <= 0:
            return
        self.player_inv[item_id] -= 1
        if self.player_inv[item_id] <= 0:
            del self.player_inv[item_id]
        if self.on_drop:
            self.on_drop(item_id, 1)
        self._flash(f"Dropped {self._display_name(item_id)}")

    def _drop_stack(self, item_id: str, qty: int) -> None:
        if qty <= 0:
            return
        self.player_inv.pop(item_id, None)
        if self.on_drop:
            self.on_drop(item_id, qty)
        self._flash(f"Dropped {qty}x {self._display_name(item_id)}")
