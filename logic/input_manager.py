"""logic/input_manager.py — Intent-based input layer.

Sits between raw pygame events and game actions.  The scene feeds in
raw events; the manager maps them to *intents* based on the current
**input context** (gameplay, ui, editor, text_input).

Other systems read the intents — they never touch raw keycodes.

Usage (in world_scene):

    self.input = InputManager()
    # each frame:
    self.input.begin_frame()
    for event in events:
        self.input.feed(event)
    self.input.end_frame()          # captures held-key state

    if self.input.just("attack"):   # discrete press
        ...
    if self.input.held("move_up"):  # continuous hold
        ...
    move = self.input.movement()    # → (dx, dy) normalised
"""

from __future__ import annotations
from enum import Enum, auto
import pygame


# ── Input contexts ──────────────────────────────────────────────────

class InputContext(Enum):
    """Determines which key-bindings are active."""
    GAMEPLAY = auto()   # normal world interaction
    UI       = auto()   # inventory / container modal open
    EDITOR   = auto()   # tile editor mode
    TEXT     = auto()    # typing into a text field


# ── Intent names (strings for flexibility, not an enum) ─────────────
# Gameplay:  move_up  move_down  move_left  move_right
#            attack  interact  inventory  save
#            weapon_1 .. weapon_4
#            toggle_debug  toggle_grid  spawn_test
#            toggle_editor  debug_scene  entity_dump  toggle_zones
# UI:        ui_up  ui_down  ui_left  ui_right  ui_confirm  ui_close
#            ui_equip  ui_use  ui_transfer
# Editor:    ed_save  ed_exit  ed_teleporter  ed_move  ed_anchor
#            ed_new_zone  ed_rename_zone  ed_brush_up  ed_brush_down
#            ed_tile_0 .. ed_tile_9
# Mouse:     click_primary  click_secondary


# ── Default key bindings ────────────────────────────────────────────

# Each binding is  (pygame key constant, modifier mask or 0)
# For mouse buttons we use negative constants: -1 = LMB, -3 = RMB

_GAMEPLAY_BINDS: dict[str, list[tuple[int, int]]] = {
    # Movement  (held — continuous)
    "move_up":      [(pygame.K_w, 0), (pygame.K_UP, 0)],
    "move_down":    [(pygame.K_s, 0), (pygame.K_DOWN, 0)],
    "move_left":    [(pygame.K_a, 0), (pygame.K_LEFT, 0)],
    "move_right":   [(pygame.K_d, 0), (pygame.K_RIGHT, 0)],
    # Actions  (press — discrete)
    "attack":       [(pygame.K_x, 0), (-1, 0)],   # X or LMB
    "interact":     [(pygame.K_e, 0), (-3, 0)],    # E or RMB
    "inventory":    [(pygame.K_i, 0)],
    "save":         [(pygame.K_s, pygame.KMOD_SHIFT)],
    "weapon_1":     [(pygame.K_1, 0)],
    "weapon_2":     [(pygame.K_2, 0)],
    "weapon_3":     [(pygame.K_3, 0)],
    "weapon_4":     [(pygame.K_4, 0)],
    # Debug / toggles
    "toggle_debug": [(pygame.K_TAB, 0)],
    "toggle_grid":  [(pygame.K_g, 0)],
    "toggle_zones": [(pygame.K_F3, 0)],
    "debug_scene":  [(pygame.K_F1, 0)],
    "entity_dump":  [(pygame.K_F2, 0)],
    "spawn_test":   [(pygame.K_BACKQUOTE, 0)],
    "toggle_editor":[(pygame.K_F4, 0)],
}

_UI_BINDS: dict[str, list[tuple[int, int]]] = {
    "ui_up":        [(pygame.K_w, 0), (pygame.K_UP, 0)],
    "ui_down":      [(pygame.K_s, 0), (pygame.K_DOWN, 0)],
    "ui_left":      [(pygame.K_a, 0), (pygame.K_LEFT, 0)],
    "ui_right":     [(pygame.K_d, 0), (pygame.K_RIGHT, 0)],
    "ui_confirm":   [(pygame.K_RETURN, 0), (pygame.K_SPACE, 0)],
    "ui_close":     [(pygame.K_ESCAPE, 0), (pygame.K_i, 0)],
    "ui_equip":     [(pygame.K_e, 0)],
    "ui_use":       [(pygame.K_u, 0)],
    "ui_transfer":  [(pygame.K_t, 0)],
    "ui_tab":       [(pygame.K_TAB, 0)],
}

_EDITOR_BINDS: dict[str, list[tuple[int, int]]] = {
    # Movement still works in editor
    "move_up":      [(pygame.K_w, 0), (pygame.K_UP, 0)],
    "move_down":    [(pygame.K_s, 0), (pygame.K_DOWN, 0)],
    "move_left":    [(pygame.K_a, 0), (pygame.K_LEFT, 0)],
    "move_right":   [(pygame.K_d, 0), (pygame.K_RIGHT, 0)],
    "ed_save":      [(pygame.K_e, 0)],
    "ed_exit":      [(pygame.K_F4, 0)],
    "ed_teleporter":[(pygame.K_t, 0)],
    "ed_move":      [(pygame.K_m, 0)],
    "ed_anchor":    [(pygame.K_k, 0)],
    "ed_new_zone":  [(pygame.K_n, 0)],
    "ed_rename":    [(pygame.K_z, 0)],
    "ed_brush_up":  [(pygame.K_RIGHTBRACKET, 0)],
    "ed_brush_down":[(pygame.K_LEFTBRACKET, 0)],
    "ed_tile_0":    [(pygame.K_0, 0)],
    "ed_tile_1":    [(pygame.K_1, 0)],
    "ed_tile_2":    [(pygame.K_2, 0)],
    "ed_tile_3":    [(pygame.K_3, 0)],
    "ed_tile_4":    [(pygame.K_4, 0)],
    "ed_tile_5":    [(pygame.K_5, 0)],
    "ed_tile_6":    [(pygame.K_6, 0)],
    "ed_tile_7":    [(pygame.K_7, 0)],
    "ed_tile_8":    [(pygame.K_8, 0)],
    "ed_tile_9":    [(pygame.K_9, 0)],
    # Debug toggles available everywhere
    "toggle_debug": [(pygame.K_TAB, 0)],
    "toggle_grid":  [(pygame.K_g, 0)],
}


# ── InputManager ────────────────────────────────────────────────────

class InputManager:
    """Context-aware input mapper.

    Call ``begin_frame()`` before processing events,
    ``feed(event)`` for each pygame event,
    ``end_frame()`` after all events.

    Then use ``just(intent)`` for discrete presses and
    ``held(intent)`` for continuous holds.
    """

    def __init__(self):
        self.context: InputContext = InputContext.GAMEPLAY
        # Intents pressed *this frame* (rising edge)
        self._pressed: set[str] = set()
        # Intents currently held (key is down right now)
        self._held: set[str] = set()
        # Mouse buttons pressed this frame
        self._mouse_pressed: set[int] = set()
        # Raw text event for TEXT context
        self.text_event: pygame.event.Event | None = None
        # Stash for unhandled raw events the scene still needs (e.g. QUIT)
        self.raw_events: list[pygame.event.Event] = []

    # ── frame lifecycle ─────────────────────────────────────────

    def begin_frame(self):
        """Call at the start of each frame before feeding events."""
        self._pressed.clear()
        self._mouse_pressed.clear()
        self.text_event = None
        self.raw_events.clear()

    def feed(self, event: pygame.event.Event):
        """Feed a raw pygame event.  Maps it to intents based on context."""
        # Always stash raw events the scene might still need
        if event.type == pygame.QUIT:
            self.raw_events.append(event)
            return

        # TEXT context: only capture text-editing keys, pass nothing else
        if self.context == InputContext.TEXT:
            if event.type == pygame.KEYDOWN:
                self.text_event = event
            return

        # KEYDOWN → discrete intent
        if event.type == pygame.KEYDOWN:
            binds = self._active_binds()
            mods = pygame.key.get_mods()
            for intent, key_list in binds.items():
                for key, req_mod in key_list:
                    if key < 0:
                        continue  # mouse binding — handled in MOUSEBUTTONDOWN
                    if event.key == key:
                        if req_mod == 0 or (mods & req_mod):
                            self._pressed.add(intent)
                            break

        # MOUSEBUTTONDOWN → discrete intent
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._mouse_pressed.add(event.button)
            binds = self._active_binds()
            neg_button = -event.button  # -1 for LMB, -3 for RMB
            for intent, key_list in binds.items():
                for key, _mod in key_list:
                    if key == neg_button:
                        self._pressed.add(intent)
                        break

        else:
            # Other events (MOUSEBUTTONUP, MOUSEMOTION, etc.) —
            # pass through for scene to handle if needed
            self.raw_events.append(event)

    def end_frame(self):
        """Snapshot held-key state for continuous intents (movement)."""
        self._held.clear()
        if self.context == InputContext.TEXT:
            return
        keys = pygame.key.get_pressed()
        binds = self._active_binds()
        for intent, key_list in binds.items():
            for key, req_mod in key_list:
                if key < 0:
                    continue
                if keys[key]:
                    # For modifier-requiring binds, only count if mod held too
                    if req_mod == 0 or (pygame.key.get_mods() & req_mod):
                        self._held.add(intent)
                        break

    # ── queries ─────────────────────────────────────────────────

    def just(self, intent: str) -> bool:
        """True if the intent was triggered this frame (rising edge)."""
        return intent in self._pressed

    def held(self, intent: str) -> bool:
        """True if the intent is continuously held down."""
        return intent in self._held

    def mouse_pressed(self, button: int = 1) -> bool:
        """True if mouse *button* was clicked this frame."""
        return button in self._mouse_pressed

    def movement(self) -> tuple[float, float]:
        """Return a normalised (dx, dy) movement vector from held keys."""
        dx = 0.0
        dy = 0.0
        if self.held("move_up"):
            dy -= 1.0
        if self.held("move_down"):
            dy += 1.0
        if self.held("move_left"):
            dx -= 1.0
        if self.held("move_right"):
            dx += 1.0
        # Normalise diagonal so player doesn't move √2× faster
        if dx != 0.0 and dy != 0.0:
            mag = (dx * dx + dy * dy) ** 0.5
            dx /= mag
            dy /= mag
        return dx, dy

    def any_pressed(self) -> set[str]:
        """Return all intents pressed this frame."""
        return set(self._pressed)

    # ── internal ────────────────────────────────────────────────

    def _active_binds(self) -> dict[str, list[tuple[int, int]]]:
        if self.context == InputContext.GAMEPLAY:
            return _GAMEPLAY_BINDS
        elif self.context == InputContext.UI:
            return _UI_BINDS
        elif self.context == InputContext.EDITOR:
            return _EDITOR_BINDS
        return {}
