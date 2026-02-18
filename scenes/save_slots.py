"""scenes/save_slots.py — Save-slot picker for New Game / Load Game.

Supports 3 save slots (0-2).  Shows zone name, play-time, and date
for each populated slot.  Empty slots show "(empty)".

Two modes:
  - ``mode="new"``   — start a new game in the chosen slot (overwrites)
  - ``mode="load"``  — load an existing save (greyed-out if empty)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pygame

from core.scene import Scene
from core.save import has_save, SAVES_DIR, delete_save

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import App


NUM_SLOTS = 3

_BG           = (18, 12, 20)
_TITLE_COL    = (200, 200, 220)
_NORMAL_COL   = (180, 180, 180)
_HOVER_COL    = (255, 240, 120)
_EMPTY_COL    = (90, 90, 90)
_DIM_COL      = (80, 80, 80)
_DANGER_COL   = (220, 80, 80)


def _slot_summary(slot: int) -> str:
    """Read a one-line summary for a save slot, or '(empty)'."""
    path = SAVES_DIR / f"slot_{slot}.json"
    if not path.exists():
        return "(empty)"
    try:
        with open(path) as f:
            data: dict[str, Any] = json.load(f)
    except Exception:
        return "(corrupt)"
    zone = data.get("zone", "???")
    clock = data.get("clock", 0.0)
    mins = int(clock) // 60
    secs = int(clock) % 60
    return f"{zone}  —  {mins}m {secs}s played"


class SaveSlotMenu(Scene):
    """Choose a save slot for new-game or load-game."""

    def __init__(self, mode: str = "new") -> None:
        assert mode in ("new", "load"), f"Invalid mode: {mode}"
        self.mode = mode
        self._cursor: int = 0
        self._summaries: list[str] = []
        self._confirm_delete: int | None = None  # slot index awaiting confirm
        self._item_rects: list[pygame.Rect] = []
        self._refresh()

    def _refresh(self) -> None:
        self._summaries = [_slot_summary(i) for i in range(NUM_SLOTS)]

    # ── Scene interface ──────────────────────────────────────────

    def on_enter(self, app: "App") -> None:
        self._refresh()

    def handle_event(self, event: pygame.event.Event, app: "App") -> None:
        # Delete-confirmation sub-state
        if self._confirm_delete is not None:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_y:
                    delete_save(self._confirm_delete)
                    self._confirm_delete = None
                    self._refresh()
                elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                    self._confirm_delete = None
            return

        if event.type == pygame.KEYDOWN:
            # +1 for the "Back" entry at the end
            total = NUM_SLOTS + 1
            if event.key == pygame.K_ESCAPE:
                app.pop_scene()
            elif event.key in (pygame.K_UP, pygame.K_w):
                self._cursor = (self._cursor - 1) % total
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._cursor = (self._cursor + 1) % total
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._select(app)
            elif event.key == pygame.K_DELETE or event.key == pygame.K_x:
                # Delete save (if hovering a populated slot)
                if self._cursor < NUM_SLOTS and has_save(self._cursor):
                    self._confirm_delete = self._cursor

        elif event.type == pygame.MOUSEMOTION:
            self._update_hover(app)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._update_hover(app)
            self._select(app)

    def update(self, dt: float, app: "App") -> None:
        pass

    def draw(self, surface: pygame.Surface, app: "App") -> None:
        surface.fill(_BG)
        sw, sh = surface.get_size()

        title_text = "NEW GAME — Choose Slot" if self.mode == "new" else "LOAD GAME — Choose Slot"
        title = app.font_lg.render(title_text, True, _TITLE_COL)
        surface.blit(title, ((sw - title.get_width()) // 2, sh // 5))

        # Slot rows
        menu_y = sh // 2 - ((NUM_SLOTS + 1) * 36) // 2
        self._item_rects = []
        for i in range(NUM_SLOTS):
            is_empty = not has_save(i)
            is_sel = (i == self._cursor)

            if self.mode == "load" and is_empty:
                col = _EMPTY_COL
            elif is_sel:
                col = _HOVER_COL
            else:
                col = _NORMAL_COL

            prefix = "> " if is_sel else "  "
            label = f"{prefix}Slot {i + 1}:  {self._summaries[i]}"
            img = app.font.render(label, True, col)
            x = (sw - img.get_width()) // 2
            y = menu_y + i * 36
            rect = surface.blit(img, (x, y))
            self._item_rects.append(rect)

        # Back button
        back_sel = self._cursor == NUM_SLOTS
        back_col = _HOVER_COL if back_sel else _NORMAL_COL
        prefix = "> " if back_sel else "  "
        back_img = app.font.render(f"{prefix}Back", True, back_col)
        bx = (sw - back_img.get_width()) // 2
        by = menu_y + NUM_SLOTS * 36 + 8
        rect = surface.blit(back_img, (bx, by))
        self._item_rects.append(rect)

        # Delete confirmation overlay
        if self._confirm_delete is not None:
            cover = pygame.Surface((sw, sh), pygame.SRCALPHA)
            cover.fill((0, 0, 0, 180))
            surface.blit(cover, (0, 0))
            msg = app.font_lg.render(
                f"Delete Slot {self._confirm_delete + 1}?  [Y]es / [N]o",
                True, _DANGER_COL,
            )
            surface.blit(msg, ((sw - msg.get_width()) // 2, sh // 2))

        # Hints
        hints = "[Enter] Select   [X/Del] Delete   [Esc] Back"
        hint_img = app.font_sm.render(hints, True, _DIM_COL)
        surface.blit(hint_img, ((sw - hint_img.get_width()) // 2, sh - 28))

    # ── Internal ──────────────────────────────────────────────────

    def _update_hover(self, app: "App") -> None:
        mx, my = app.mouse_pos()
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(mx, my):
                self._cursor = i
                return

    def _select(self, app: "App") -> None:
        if self._cursor == NUM_SLOTS:
            app.pop_scene()  # Back
            return

        slot = self._cursor

        if self.mode == "new":
            self._start_new_game(app, slot)
        else:  # load
            if not has_save(slot):
                return  # can't load an empty slot
            self._load_game(app, slot)

    def _start_new_game(self, app: "App", slot: int) -> None:
        """Overwrite slot with a fresh game and enter gameplay."""
        # If a save exists, it'll be overwritten on the next save.
        from core.session import Session
        from scenes.world import TopDown

        # Clear stack back to main menu, then push game
        while len(app._scenes) > 1:
            app.pop_scene()

        session = Session(app.world)
        session.new_game("playground")
        session.save(slot)  # immediately persist to the chosen slot
        app.push_scene(TopDown(session))

    def _load_game(self, app: "App", slot: int) -> None:
        """Load an existing save and enter gameplay."""
        from core.session import Session
        from scenes.world import TopDown

        while len(app._scenes) > 1:
            app.pop_scene()

        session = Session(app.world)
        if not session.load(slot):
            # Fallback: start a new game if save is corrupt
            session.new_game("playground")
        app.push_scene(TopDown(session))
