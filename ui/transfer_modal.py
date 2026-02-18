"""ui/transfer_modal.py — Container ↔ player transfer modal.

Two side-by-side panels.  Left = container, right = player.
Items are moved freely between the two inventories.
"""

from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

from ui.modal import Modal
from ui.commands import CloseModal, UICommand
from ui.helpers import sorted_items, draw_overlay, draw_item_row, ROW_H

if TYPE_CHECKING:
    from core.app import App
    from systems.item_registry import ItemRegistry


class TransferModal(Modal):
    """Two-panel transfer overlay (player ↔ container)."""

    def __init__(
        self,
        player_inv: dict[str, int],
        container_inv: dict[str, int],
        registry: "ItemRegistry | None" = None,
        title: str = "Your Bag",
        container_title: str = "Container",
    ) -> None:
        self.player_inv = player_inv
        self.container_inv = container_inv
        self.registry = registry
        self.title = title
        self.container_title = container_title

        self.cursor: int = 0
        self.panel: int = 1  # 0 = container, 1 = player
        self.message: str = ""
        self.message_timer: float = 0.0
        self._item_rects: list[tuple[pygame.Rect, int, int]] = []
        self._hover_idx: int = -1
        self._hover_panel: int = -1

    # ── helpers ───────────────────────────────────────────────────

    def _display_name(self, item_id: str) -> str:
        if self.registry:
            return self.registry.display_name(item_id)
        return item_id

    def _sprite_info(self, item_id: str) -> tuple[str, tuple[int, int, int]]:
        if self.registry:
            return self.registry.sprite_info(item_id)
        return "?", (200, 200, 200)

    def _active_inv(self) -> dict[str, int]:
        return self.container_inv if self.panel == 0 else self.player_inv

    def _active_items(self) -> list[tuple[str, int]]:
        return sorted_items(self._active_inv())

    def _clamp_cursor(self) -> None:
        items = self._active_items()
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
        items = self._active_items()

        if key in (pygame.K_w, pygame.K_UP):
            self.cursor = max(0, self.cursor - 1)
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.cursor = min(len(items) - 1, self.cursor + 1) if items else 0
        elif key in (pygame.K_a, pygame.K_LEFT, pygame.K_d, pygame.K_RIGHT):
            self.panel = 1 - self.panel
            self.cursor = 0
            self._clamp_cursor()
        elif key in (pygame.K_ESCAPE, pygame.K_e):
            cmds.append(CloseModal())
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if items:
                item_id, _qty = items[min(self.cursor, len(items) - 1)]
                self._transfer_item(item_id)
                self._clamp_cursor()

        return cmds

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        sw, sh = surface.get_size()
        self._item_rects.clear()
        draw_overlay(surface)

        total_w = 560
        total_h = min(sh - 60, 460)
        base_x = (sw - total_w) // 2
        base_y = (sh - total_h) // 2
        panel_w = total_w // 2 - 6

        for p_idx in range(2):
            px = base_x + p_idx * (panel_w + 12)
            py = base_y
            is_active = (self.panel == p_idx)

            bg = (40, 40, 65) if is_active else (30, 30, 45)
            border = (160, 160, 200) if is_active else (80, 80, 100)
            pygame.draw.rect(surface, bg, (px, py, panel_w, total_h))
            pygame.draw.rect(surface, border, (px, py, panel_w, total_h), 2)

            title = self.container_title if p_idx == 0 else self.title
            pygame.draw.rect(surface, (50, 50, 75), (px, py, panel_w, 28))
            app.draw_text(surface, title, px + 10, py + 6,
                          (200, 200, 255), font=app.font)

            inv = self.container_inv if p_idx == 0 else self.player_inv
            items = sorted_items(inv or {})
            iy = py + 36

            if items:
                for idx, (item_id, qty) in enumerate(items):
                    is_sel = is_active and idx == self.cursor
                    is_hover = (idx == self._hover_idx
                                and p_idx == self._hover_panel)
                    char, color = self._sprite_info(item_id)
                    name = self._display_name(item_id)

                    row = draw_item_row(
                        surface, app, px + 3, iy, panel_w - 6,
                        char=char, color=color, name=name, qty=qty,
                        selected=is_sel, hovered=is_hover,
                    )
                    self._item_rects.append((row, p_idx, idx))
                    iy += ROW_H
                    if iy > py + total_h - 50:
                        app.draw_text(surface, "  ...", px + 24, iy,
                                      (150, 150, 150), font=app.font_sm)
                        break
            else:
                app.draw_text(surface, "  (empty)", px + 10, iy,
                              (120, 120, 140), font=app.font_sm)

        # Flash message
        if self.message and self.message_timer > 0:
            app.draw_text(surface, self.message, base_x + 14,
                          base_y + total_h - 44,
                          (100, 255, 140), font=app.font_sm)

        # Controls
        app.draw_text(
            surface,
            "[Click] Transfer  [Shift+Click] Stack  [A/D] Panel  [E/Esc] Close",
            base_x + 10, base_y + total_h + 2,
            (100, 180, 100), font=app.font_sm,
        )

    # ── mouse ────────────────────────────────────────────────────

    def _handle_mouse_motion(self, event: pygame.event.Event) -> None:
        mx, my = event.pos
        self._hover_idx = -1
        self._hover_panel = -1
        for rect, p_idx, idx in self._item_rects:
            if rect.collidepoint(mx, my):
                self._hover_idx = idx
                self._hover_panel = p_idx
                if self.panel != p_idx:
                    self.panel = p_idx
                self.cursor = idx
                break

    def _handle_mouse_click(self, event: pygame.event.Event) -> list[UICommand]:
        cmds: list[UICommand] = []
        mx, my = event.pos
        mods = pygame.key.get_mods()

        for rect, p_idx, idx in self._item_rects:
            if not rect.collidepoint(mx, my):
                continue
            if self.panel != p_idx:
                self.panel = p_idx
            self.cursor = idx
            items = self._active_items()
            if not items or idx >= len(items):
                return cmds
            item_id, qty = items[idx]

            if event.button == 1:
                if mods & pygame.KMOD_SHIFT:
                    self._transfer_stack(item_id, qty)
                else:
                    self._transfer_item(item_id)
                self._clamp_cursor()
            elif event.button == 3:
                self._transfer_item(item_id)
                self._clamp_cursor()
            return cmds

        return cmds

    # ── transfer ─────────────────────────────────────────────────

    def _transfer_item(self, item_id: str) -> None:
        if self.panel == 0:
            src, dst = self.container_inv, self.player_inv
            verb = "Took"
        else:
            src, dst = self.player_inv, self.container_inv
            verb = "Stored"

        if src.get(item_id, 0) <= 0:
            return

        src[item_id] -= 1
        if src[item_id] <= 0:
            del src[item_id]
        dst[item_id] = dst.get(item_id, 0) + 1
        self._flash(f"{verb} {self._display_name(item_id)}")

    def _transfer_stack(self, item_id: str, qty: int) -> None:
        if self.panel == 0:
            src, dst = self.container_inv, self.player_inv
            verb = "Took"
        else:
            src, dst = self.player_inv, self.container_inv
            verb = "Stored"

        actual = src.get(item_id, 0)
        if actual <= 0:
            return
        src.pop(item_id, None)
        dst[item_id] = dst.get(item_id, 0) + actual
        self._flash(f"{verb} {actual}x {self._display_name(item_id)}")
