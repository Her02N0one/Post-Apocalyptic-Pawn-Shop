"""editor/app.py — Standalone editor application.

Owns the Pygame window, main loop, font management, and routes
events/drawing to all sub-systems (toolbar, canvas, palette,
inspector, modals, loot editor, template editor).

Usage::

    from editor.app import EditorApp
    EditorApp().run()            # opens blank zone
    EditorApp("playground").run()  # opens named zone
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

# Ensure project root on sys.path for standalone launch
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.fonts import get_font
from editor.ui import Theme, UIContext
from editor.input_manager import InputManager
from editor.state import EditorState, Tool, list_zones
from editor.canvas import Canvas
from editor.panels import (
    MenuBar, TilePalette, ZonePanel, EntityPanel,
    TextureBrowserPanel, PortalPanel, RoomTemplatePanel,
    Minimap, StatusBar, ZoneNav, PanelSplitter, PanelTabs,
    Toolbar, EditorChrome,
)
from editor.inspector import Inspector
from editor.modals import (
    ModalManager, TileEditorModal,
)
from editor.loot_editor import LootTableEditor
from editor.templates import TemplateEditor
from editor.entity_forge import EntityForgeModal
from editor.fp_preview import FPPreview
from editor.layout import Layout
from editor.actions import ActionsMixin
from editor.canvas_events import CanvasEventsMixin
from systems.textures import TextureAtlas


# ═════════════════════════════════════════════════════════════════════

class EditorApp(ActionsMixin, CanvasEventsMixin):
    """Self-contained Pygame application for the map editor."""

    TITLE = "Post-Apocalyptic Pawn Shop \u2014 Map Editor"
    MIN_W, MIN_H = 960, 640
    FPS = 60

    def __init__(self, zone_name: str = ""):
        self._initial_zone = zone_name
        self._running = False

    # ── Initialise ──────────────────────────────────────────────

    def _init(self):
        pygame.init()

        # Pick a comfortable starting size (80% of the display)
        info = pygame.display.Info()
        start_w = max(self.MIN_W, int(info.current_w * 0.80))
        start_h = max(self.MIN_H, int(info.current_h * 0.80))

        self.screen = pygame.display.set_mode(
            (start_w, start_h),
            pygame.RESIZABLE,
        )
        pygame.display.set_caption(self.TITLE)
        self.clock = pygame.time.Clock()

        # Initial layout compute (sets Layout.scale)
        Layout.update(start_w, start_h)

        # Fonts — built from scale factor
        self._build_fonts()

        # Shared context
        self.ctx = UIContext()
        self.state = EditorState()

        # Sub-systems
        self.canvas = Canvas(self.state)
        self.menu_bar = MenuBar(self.state, self.ctx)
        self.zone_nav = ZoneNav(self.state)
        self.atlas = TextureAtlas()
        self.palette = TilePalette(self.state, self.ctx, atlas=self.atlas)
        self.zone_panel = ZonePanel(self.state)
        self.entity_panel = EntityPanel(self.state)
        self.texture_panel = TextureBrowserPanel(self.state, atlas=self.atlas)
        self.portal_panel = PortalPanel(self.state)
        self.template_panel = RoomTemplatePanel(self.state)
        self.minimap = Minimap(self.state)
        self.status = StatusBar(self.state)
        self.inspector = Inspector(self.state, self.ctx, atlas=self.atlas)
        self.modals = ModalManager(self.state, self.ctx)
        self.loot_editor = LootTableEditor(self.state, self.ctx)
        self.template_editor = TemplateEditor(self.state, self.ctx)
        self.forge = EntityForgeModal(self.ctx, self.state)
        self.fp_preview = FPPreview()
        self.splitter = PanelSplitter()
        self.panel_tabs = PanelTabs()
        self.toolbar = Toolbar()
        self.chrome = EditorChrome(self.panel_tabs)

        # Table-driven left panel lookup (panel_mode → widget)
        self._panel_widgets: dict[str, object] = {
            "tiles":     self.palette,
            "zones":     self.zone_panel,
            "entities":  self.entity_panel,
            "textures":  self.texture_panel,
            "portals":   self.portal_panel,
            "templates": self.template_panel,
        }

        # ── Input layer system ──────────────────────────────────
        self.input = InputManager(self.ctx, on_action=self._dispatch_action)
        self._register_input_layers()

        # Load initial zone (or start blank)
        if self._initial_zone:
            if not self.state.load_zone(self._initial_zone):
                self.state.new_zone(self._initial_zone, 30, 20)
        else:
            self.state.new_zone("", 30, 20)

    # ── Shared helpers (eliminate duplicated logic) ──────────────

    def _do_delete_entity(self):
        """Delete the currently selected entity."""
        st = self.state
        if 0 <= st.selected_entity < len(st.entities):
            st.delete_entity(st.selected_entity)
            st.selected_entity = -1
            self.inspector.force_rebuild()
            st.toast("Entity deleted")

    def _do_undo(self):
        self.state.undo()
        self.inspector.force_rebuild()

    def _do_redo(self):
        self.state.redo()
        self.inspector.force_rebuild()

    def _do_load_zone(self, name: str):
        """Load a zone by name and refresh the inspector."""
        self.state.load_zone(name)
        self.inspector.force_rebuild()
        # Reset FP camera to the centre of the new zone
        if self.fp_preview.active:
            st = self.state
            self.fp_preview.sync_to_anchor((st.map_w / 2.0, st.map_h / 2.0))

    def _build_fonts(self):
        """(Re)create fonts at sizes appropriate for the current scale."""
        s = Layout.scale
        self.font = get_font(max(12, round(16 * s)))
        self.font_sm = get_font(max(10, round(12 * s)))
        Layout._fonts_dirty = False

    # ── Main loop ───────────────────────────────────────────────

    def run(self):
        self._init()
        self._running = True

        while self._running:
            dt = self.clock.tick(self.FPS) / 1000.0
            self._handle_events()
            self._update(dt)
            self._draw(dt)
            pygame.display.flip()

        pygame.quit()

    # ── Events ──────────────────────────────────────────────────

    def _handle_events(self):
        # Ensure layout is up-to-date before processing events
        # (handles the frame where a window resize occurs)
        Layout.update(*self.screen.get_size())
        if Layout._fonts_dirty:
            self._build_fonts()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                continue
            self.input.dispatch(event)

    # ── Input layer registration ────────────────────────────────

    def _register_input_layers(self):
        """Register all event-handling layers in priority order."""
        add = self.input.add

        # Full-screen overlays — always consume when active
        add("overlays", 100,
            lambda: (self.forge.active or self.loot_editor.active
                     or self.template_editor.active or self.modals.active),
            self._layer_overlays)

        # Global keyboard shortcuts (Ctrl+S, G, M, R, etc.)
        add("shortcuts", 90,
            lambda: True,
            self._layer_shortcuts)

        # Menu bar — dropdowns block mouse events when open
        add("menu", 80,
            lambda: True,
            self._layer_menu)

        # Zone navigation bar (back / forward / connected zone links)
        add("zone_nav", 70,
            lambda: True,
            self._layer_zone_nav)

        # Tool strip (brush / eraser / fill / select / picker)
        add("toolbar", 65,
            lambda: True,
            self._layer_toolbar)

        # Draggable panel splitter handles
        add("splitter", 60,
            lambda: True,
            self._layer_splitter)

        # FP fullscreen editing (consumes ALL events when active)
        add("fp_fullscreen", 55,
            lambda: self.fp_preview.active and self.fp_preview.fullscreen,
            self._layer_fp_fullscreen)

        # Left-panel tab strip
        add("panel_tabs", 50,
            lambda: True,
            self._layer_panel_tabs)

        # Active left panel (tile palette, zone list, entity panel, etc.)
        add("left_panel", 45,
            lambda: True,
            self._layer_left_panel)

        # Right panel (tabbed inspector)
        add("inspector", 40,
            lambda: True,
            self._layer_inspector)

        # FP picture-in-picture (WASD / arrows when active but not fullscreen)
        add("fp_pip", 35,
            lambda: self.fp_preview.active,
            self._layer_fp_pip)

        # Canvas (tile grid — default fallthrough)
        add("canvas", 30,
            lambda: True,
            self._layer_canvas)

    # ── Layer handlers ──────────────────────────────────────────

    def _layer_overlays(self, event):
        """Full-screen overlays always consume all events."""
        if self.forge.active:
            result = self.forge.handle_event(event)
            if result == "place":
                self._begin_forge_placement()
                self.entity_panel.refresh()
            return True
        if self.loot_editor.active:
            self.loot_editor.handle_event(event)
            return True
        if self.template_editor.active:
            self.template_editor.handle_event(event)
            return True
        if self.modals.active:
            self.modals.handle_event(event)
            return True
        return None

    def _layer_shortcuts(self, event):
        """Global keyboard shortcuts."""
        if event.type != pygame.KEYDOWN:
            return None
        if self._handle_shortcut(event):
            return True
        return None

    def _layer_menu(self, event):
        """Menu bar — returns action strings, blocks mouse when open."""
        action = self.menu_bar.handle_event(event)
        if action:
            if action != MenuBar._CONSUMED:
                return action  # action string
            return True  # consumed internally
        # Block mouse events while a dropdown is open
        if self.menu_bar.is_open:
            if event.type in (pygame.MOUSEBUTTONDOWN,
                              pygame.MOUSEBUTTONUP,
                              pygame.MOUSEMOTION):
                return True
        return None

    def _layer_zone_nav(self, event):
        """Zone navigation bar — back/forward/connected zones."""
        nav_action = self.zone_nav.handle_event(event)
        if nav_action and nav_action.startswith("nav:"):
            self._do_load_zone(nav_action[4:])
            return True
        return None

    def _layer_toolbar(self, event):
        """Tool strip — produces 'tool:name' actions."""
        action = self.toolbar.handle_event(event)
        if action:
            return action  # action string dispatched by InputManager
        return None

    def _layer_splitter(self, event):
        """Draggable panel dividers."""
        if self.splitter.handle_event(event):
            return True
        return None

    def _layer_fp_fullscreen(self, event):
        """FP fullscreen editing mode."""
        if self.fp_preview.handle_event(event, self.state):
            return True
        return None

    def _layer_panel_tabs(self, event):
        """Left-panel tab strip — produces 'panel:mode' actions."""
        action = self.panel_tabs.handle_event(event)
        if action:
            return action  # action string
        return None

    def _layer_left_panel(self, event):
        """Active left panel — routes events and handles results."""
        result = self._handle_left_panel_event(event)
        if result is not None:
            return True  # consumed (actions dispatched internally)
        return None

    def _layer_inspector(self, event):
        """Right panel inspector — produces action strings."""
        action = self.inspector.handle_event(event, self.screen)
        if action:
            return action  # action string
        return None

    def _layer_fp_pip(self, event):
        """FP picture-in-picture WASD / mouse."""
        if self.fp_preview.handle_event(event, self.state):
            return True
        return None

    def _layer_canvas(self, event):
        """Canvas interaction — tile grid mouse events."""
        self._handle_canvas_event(event)
        return None  # canvas is the final fallthrough

    # ── Left-panel event routing ────────────────────────────────

    def _handle_left_panel_event(self, event: pygame.event.Event) -> str | None:
        """Dispatch event to the active left panel and handle its result.

        Returns the result string (truthy) if the event was consumed,
        or *None* when the panel didn't handle the event.
        """
        widget = self._panel_widgets.get(self.menu_bar.panel_mode)
        if widget is None:
            return None

        result = widget.handle_event(event, self.screen)
        if result is None:
            return None

        # "consumed" means the widget ate the event but there's no action
        if result == "consumed":
            return result

        # Tile-palette specials (not in the generic dispatch tables)
        if result == "add_tile":
            self.modals.open(
                TileEditorModal(self.modals, atlas=self.atlas))
            return result

        if result.startswith("edit_tile:"):
            tile_id = result.split(":", 1)[1]
            from core.tiles import TILE_REGISTRY
            td = TILE_REGISTRY.get(tile_id)
            if td is not None:
                self.modals.open(
                    TileEditorModal(self.modals, edit_tile=td,
                                    atlas=self.atlas))
            return result

        # Zone-panel special: load a zone directly
        if result.startswith("load:"):
            self._do_load_zone(result.split(":", 1)[1])
            return result

        # Everything else → generic dispatch
        self._dispatch_action(result)
        return result

    def _handle_shortcut(self, event: pygame.event.Event) -> bool:
        """Global keyboard shortcuts.  Returns True if handled."""
        key = event.key
        mod = event.mod
        st = self.state

        # When a text field is focused, only allow Ctrl combos through;
        # all other keys belong to the text field.
        if self.ctx.any_focused() and not (mod & pygame.KMOD_CTRL):
            return False

        # When FP fullscreen is active, only allow Ctrl combos through;
        # all other keys belong to the FP editor.
        if self.fp_preview.active and self.fp_preview.fullscreen:
            if not (mod & pygame.KMOD_CTRL):
                return False

        if key == pygame.K_s and mod & pygame.KMOD_CTRL:
            st.save_zone()
            return True
        if key == pygame.K_z and mod & pygame.KMOD_CTRL:
            self._do_undo()
            return True
        if key == pygame.K_y and mod & pygame.KMOD_CTRL:
            self._do_redo()
            return True
        if key == pygame.K_g:
            st.show_grid = not st.show_grid
            return True
        if key == pygame.K_m:
            st.show_minimap = not st.show_minimap
            return True
        if key == pygame.K_r and not mod & pygame.KMOD_CTRL:
            _DIRS = ("N", "E", "S", "W")
            st.pending_rotation = (st.pending_rotation + 1) % 4
            st.toast(f"Rotation: {_DIRS[st.pending_rotation]}")
            return True
        if key == pygame.K_LEFTBRACKET:
            st.brush_size = max(1, st.brush_size - 1)
            return True
        if key == pygame.K_RIGHTBRACKET:
            st.brush_size = min(9, st.brush_size + 1)
            return True
        if key == pygame.K_p and not mod & pygame.KMOD_CTRL:
            self._do_fp_preview()
            return True
        if key == pygame.K_f and not mod & pygame.KMOD_CTRL:
            self._do_fp_edit()
            return True
        if key == pygame.K_DELETE:
            self._do_delete_entity()
            return True
        if key == pygame.K_ESCAPE and st.pending_prefab:
            st.pending_prefab = ""
            st.toast("Placement cancelled")
            return True

        # Tool shortcuts
        _TOOL_KEYS = {
            pygame.K_v: Tool.SELECT,
            pygame.K_b: Tool.BRUSH,
            pygame.K_e: Tool.ERASER,
            pygame.K_i: Tool.FILL,
        }
        if key in _TOOL_KEYS and not mod & pygame.KMOD_CTRL:
            st.tool = _TOOL_KEYS[key]
            return True

        # Number keys → cycle through sorted tile palette
        if pygame.K_0 <= key <= pygame.K_9 and not mod & pygame.KMOD_CTRL:
            from core.tiles import TILE_REGISTRY
            ids = sorted(TILE_REGISTRY.keys())
            if ids:
                idx = (key - pygame.K_0) % len(ids)
                st.selected_tile = ids[idx]
                if st.tool not in (Tool.BRUSH, Tool.FILL):
                    st.tool = Tool.BRUSH
                st.toast(f"Tile: {st.selected_tile}")
                return True

        return False

    # ── Update ──────────────────────────────────────────────────

    def _update(self, dt: float):
        st = self.state
        if st.toast_timer > 0:
            st.toast_timer -= dt
        # Update FP preview camera movement
        # Skip when a full-screen overlay is active to prevent camera drift
        if self.fp_preview.active and not (
                self.forge.active or self.loot_editor.active
                or self.template_editor.active or self.modals.active):
            self.fp_preview.update(dt, st.tiles, st.map_w, st.map_h)
        # Cursor: resize arrow when hovering a splitter
        cur = self.splitter.cursor()
        if cur is not None:
            pygame.mouse.set_cursor(cur)
        else:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

    # ── Draw ────────────────────────────────────────────────────

    def _draw(self, dt: float):
        screen = self.screen

        # Recompute responsive layout for current window size
        # (must be before anything else, including overlay early-returns)
        Layout.update(*screen.get_size())
        if Layout._fonts_dirty:
            self._build_fonts()

        # Full-screen overlays
        if self.forge.active:
            self.forge.draw(screen, self.font, self.font_sm, dt)
            return
        if self.loot_editor.active:
            self.loot_editor.draw(screen, self.font, self.font_sm, dt)
            return
        if self.template_editor.active:
            self.template_editor.draw(screen, self.font, self.font_sm, dt)
            return

        screen.fill(Theme.BG)

        # All chrome: backgrounds + borders for every panel region
        self.chrome.draw_backgrounds(screen)

        # Canvas (map) — drawn into the gap between left/right panels
        self.canvas.draw(screen, self.font, self.font_sm)

        # Horizontal bars (content only — chrome drew their backgrounds)
        self.zone_nav.draw(screen, self.font_sm)
        self.toolbar.draw(screen, self.font_sm, self.state.tool)
        self.status.draw(screen, self.font_sm)

        # Left panel — tabs, then content
        self.chrome.draw_left_tabs(screen, self.font_sm,
                                    self.menu_bar.panel_mode)
        panel_widget = self._panel_widgets.get(self.menu_bar.panel_mode)
        if panel_widget is not None:
            panel_widget.draw(screen, self.font, self.font_sm)

        # Minimap (floats over canvas)
        self.minimap.draw(screen, self.font_sm)

        # Right panel (inspector content — chrome drew its background)
        self.inspector.draw(screen, self.font, self.font_sm, dt)

        # Pending entity placement indicator
        if self.state.pending_prefab:
            self._draw_placement_hint(screen)

        # FP Preview (picture-in-picture OR fullscreen over the canvas)
        if self.fp_preview.active:
            L = Layout
            if self.fp_preview.fullscreen:
                fp_rect = pygame.Rect(
                    L.canvas_x, L.canvas_y,
                    L.canvas_w, L.canvas_h,
                )
            else:
                pw = min(400, L.canvas_w // 2)
                ph = min(300, L.canvas_h // 2)
                fp_rect = pygame.Rect(
                    L.canvas_x + L.canvas_w - pw - 8,
                    L.canvas_y + 8,
                    pw, ph,
                )
            self.fp_preview.draw(
                screen, self.state.tiles,
                self.state.map_w, self.state.map_h, fp_rect,
                selected_tile=self.state.selected_tile,
                entities=self.state.entities,
                rotations=self.state.rotations,
                pending_rotation=self.state.pending_rotation,
                floor_heights=self.state.floor_heights,
                ceil_heights=self.state.ceil_heights)

        # Panel splitter handles (drawn over panel borders)
        self.splitter.draw(screen)

        # Deferred chrome overlays (tooltips, drag previews)
        self.chrome.draw_overlays(screen)

        # Menu bar drawn last so dropdowns overlap everything
        self.menu_bar.draw(screen, self.font, self.font_sm)

        # Modals on top
        if self.modals.active:
            self.modals.draw(screen, self.font, self.font_sm, dt)

    def _draw_placement_hint(self, screen: pygame.Surface):
        """Draw a small banner when entity placement is pending."""
        L = Layout
        name = self.state.pending_prefab
        if name.startswith("forge:"):
            name = name[6:]
        hint = f"Placing: {name}  |  Click map \u00b7 Esc/RClick cancel"
        hw = self.font_sm.size(hint)[0] + 20
        hx = L.canvas_x + (L.canvas_w - hw) // 2
        hy = L.canvas_y + 4
        bg = pygame.Surface((hw, 22), pygame.SRCALPHA)
        bg.fill((40, 80, 40, 200))
        screen.blit(bg, (hx, hy))
        from editor.ui import draw_text
        draw_text(screen, hint, hx + 10, hy + 4, Theme.SUCCESS, self.font_sm)