"""ui.inventory_modal — Player inventory modal.

Single-panel overlay for browsing items, equipping weapons/armor, and
using consumables.  Equip/unequip mutates the held ``Equipment``
reference directly (it's an ECS component pointer).  Cross-boundary
effects (healing) are emitted as ``HealPlayer`` commands.
"""

from __future__ import annotations
import pygame

from ui.modal import Modal
from ui.commands import CloseModal, HealPlayer, UICommand
from ui.helpers import (
    sorted_items, draw_overlay, draw_title_bar, draw_item_row, ROW_H,
)


class InventoryModal(Modal):
    """Full-screen inventory overlay (player bag)."""

    def __init__(
        self,
        player_inv: dict[str, int],
        equipment=None,
        registry=None,
        title: str = "Inventory",
    ) -> None:
        self.player_inv = player_inv
        self.equipment = equipment   # Equipment component (or None)
        self.registry = registry     # ItemRegistry resource (or None)
        self.title = title

        # UI state
        self.cursor: int = 0
        self.message: str = ""
        self.message_timer: float = 0.0

        # Hit-test rects: [(rect, item_index), …]
        self._item_rects: list[tuple[pygame.Rect, int]] = []
        self._hover_idx: int = -1

    # ── helpers ─────────────────────────────────────────────────────

    def _display_name(self, item_id: str) -> str:
        if self.registry is not None:
            return self.registry.display_name(item_id)
        return item_id

    def _sprite_info(self, item_id: str):
        if self.registry is not None:
            return self.registry.sprite_info(item_id)
        return "?", (200, 200, 200)

    def _item_type(self, item_id: str) -> str:
        if self.registry is not None:
            return self.registry.item_type(item_id)
        return "misc"

    def _items(self) -> list[tuple[str, int]]:
        return sorted_items(self.player_inv)

    def _is_equipped(self, item_id: str) -> bool:
        eq = self.equipment
        if eq is None:
            return False
        return eq.weapon == item_id or eq.armor == item_id

    def _clamp_cursor(self) -> None:
        items = self._items()
        if self.cursor >= len(items):
            self.cursor = max(0, len(items) - 1)

    def _flash(self, msg: str) -> None:
        self.message = msg
        self.message_timer = 1.5

    # ── Modal interface ─────────────────────────────────────────────

    def update(self, dt: float) -> None:
        if self.message_timer > 0:
            self.message_timer -= dt

    def handle_event(self, event: pygame.event.Event) -> list[UICommand]:
        cmds: list[UICommand] = []

        # Mouse
        if event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(event)
            return cmds
        if event.type == pygame.MOUSEBUTTONDOWN:
            return self._handle_mouse_click(event)

        if event.type != pygame.KEYDOWN:
            return cmds

        key = event.key
        items = self._items()

        # Navigation
        if key in (pygame.K_w, pygame.K_UP):
            self.cursor = max(0, self.cursor - 1)
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.cursor = min(len(items) - 1, self.cursor + 1) if items else 0

        # Close
        elif key in (pygame.K_ESCAPE, pygame.K_i):
            cmds.append(CloseModal())

        # Interact (equip / use)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if items:
                item_id, _qty = items[min(self.cursor, len(items) - 1)]
                cmds.extend(self._interact_item(item_id))
                self._clamp_cursor()

        # Drop single
        elif key == pygame.K_q:
            if items:
                item_id, _qty = items[min(self.cursor, len(items) - 1)]
                self._drop_item(item_id)
                self._clamp_cursor()

        return cmds

    def draw(self, surface: pygame.Surface, app) -> None:
        sw, sh = surface.get_size()
        self._item_rects.clear()

        draw_overlay(surface)

        modal_w = 440
        modal_h = min(sh - 60, 500)
        mx = (sw - modal_w) // 2
        my = (sh - modal_h) // 2

        # Panel chrome
        pygame.draw.rect(surface, (35, 35, 55), (mx, my, modal_w, modal_h))
        pygame.draw.rect(surface, (140, 140, 180), (mx, my, modal_w, modal_h), 2)
        draw_title_bar(surface, app, mx, my, modal_w, self.title)

        y = my + 38

        # Equipment summary
        eq = self.equipment
        weapon_name = "(fists)"
        armor_name = "(none)"
        if eq:
            if eq.weapon:
                weapon_name = self._display_name(eq.weapon)
            if eq.armor:
                armor_name = self._display_name(eq.armor)
        app.draw_text(surface, f"Weapon: {weapon_name}", mx + 14, y,
                      (180, 180, 220), font=app.font_sm)
        y += 18
        app.draw_text(surface, f"Armor:  {armor_name}", mx + 14, y,
                      (180, 180, 220), font=app.font_sm)
        y += 24

        # Divider
        pygame.draw.line(surface, (80, 80, 100),
                         (mx + 10, y), (mx + modal_w - 10, y))
        y += 6

        # Item list
        items = self._items()
        if items:
            for idx, (item_id, qty) in enumerate(items):
                char, color = self._sprite_info(item_id)
                name = self._display_name(item_id)
                row = draw_item_row(
                    surface, app, mx + 4, y, modal_w - 8,
                    char=char, color=color, name=name, qty=qty,
                    equipped=self._is_equipped(item_id),
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

        # Controls hint
        app.draw_text(
            surface,
            "[Click] Equip/Use  [Shift+Click] Drop Stack  [RMB] Act  [I/Esc] Close",
            mx + 10, my + modal_h - 24, (100, 180, 100), font=app.font_sm,
        )

    # ── mouse ───────────────────────────────────────────────────────

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

            if event.button == 1:  # left click
                if mods & pygame.KMOD_SHIFT:
                    self._drop_stack(item_id, qty)
                else:
                    cmds.extend(self._interact_item(item_id))
                self._clamp_cursor()
            elif event.button == 3:  # right click
                cmds.extend(self._interact_item(item_id))
                self._clamp_cursor()
            return cmds

        return cmds

    # ── item actions ────────────────────────────────────────────────

    def _interact_item(self, item_id: str) -> list[UICommand]:
        cmds: list[UICommand] = []
        itype = self._item_type(item_id)

        if itype == "weapon":
            eq = self.equipment
            if eq is None:
                return cmds
            if eq.weapon == item_id:
                eq.weapon = ""
                self._flash(f"Unequipped {self._display_name(item_id)}")
            else:
                eq.weapon = item_id
                self._flash(f"Equipped {self._display_name(item_id)}")

        elif itype == "armor":
            eq = self.equipment
            if eq is None:
                return cmds
            if eq.armor == item_id:
                eq.armor = ""
                self._flash(f"Unequipped {self._display_name(item_id)}")
            else:
                eq.armor = item_id
                self._flash(f"Equipped {self._display_name(item_id)}")

        elif itype == "consumable":
            cmds.extend(self._use_consumable(item_id))

        else:
            self._flash("Can't use that")

        return cmds

    def _use_consumable(self, item_id: str) -> list[UICommand]:
        cmds: list[UICommand] = []
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
        return cmds

    def _drop_item(self, item_id: str) -> None:
        if self.player_inv.get(item_id, 0) <= 0:
            return
        self._unequip_if_needed(item_id)
        self.player_inv[item_id] -= 1
        if self.player_inv[item_id] <= 0:
            del self.player_inv[item_id]
        self._flash(f"Dropped {self._display_name(item_id)}")

    def _drop_stack(self, item_id: str, qty: int) -> None:
        if qty <= 0:
            return
        self._unequip_if_needed(item_id)
        self.player_inv.pop(item_id, None)
        self._flash(f"Dropped {qty}x {self._display_name(item_id)}")

    def _unequip_if_needed(self, item_id: str) -> None:
        eq = self.equipment
        if eq is None:
            return
        if eq.weapon == item_id:
            eq.weapon = ""
        if eq.armor == item_id:
            eq.armor = ""
