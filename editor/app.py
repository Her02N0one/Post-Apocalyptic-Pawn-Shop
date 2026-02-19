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

from editor.ui import Theme, UIContext
from editor.state import EditorState, Tool, list_zones
from editor.canvas import Canvas
from editor.panels import MenuBar, TilePalette, ZonePanel, Minimap, StatusBar, ZoneNav
from editor.inspector import Inspector
from editor.modals import (
    ModalManager, TextInputModal, ZonePickerModal,
    PrefabPickerModal, AddComponentModal, PortalWizardModal,
)
from editor.loot_editor import LootTableEditor
from editor.templates import TemplateEditor
from editor.layout import Layout


# ═════════════════════════════════════════════════════════════════════

class EditorApp:
    """Self-contained Pygame application for the map editor."""

    TITLE = "Post-Apocalyptic Pawn Shop — Map Editor"
    MIN_W, MIN_H = 960, 640
    FPS = 60

    def __init__(self, zone_name: str = ""):
        self._initial_zone = zone_name
        self._running = False

    # ── Initialise ──────────────────────────────────────────────

    def _init(self):
        pygame.init()
        self.screen = pygame.display.set_mode(
            (self.MIN_W, self.MIN_H),
            pygame.RESIZABLE | pygame.SCALED,
        )
        pygame.display.set_caption(self.TITLE)
        self.clock = pygame.time.Clock()

        # Fonts
        self.font = pygame.font.SysFont("monospace", 16)
        self.font_sm = pygame.font.SysFont("monospace", 12)

        # Initial layout compute
        Layout.update(self.MIN_W, self.MIN_H)

        # Shared context
        self.ctx = UIContext()
        self.state = EditorState()

        # Sub-systems
        self.canvas = Canvas(self.state)
        self.menu_bar = MenuBar(self.state, self.ctx)
        self.zone_nav = ZoneNav(self.state)
        self.palette = TilePalette(self.state)
        self.zone_panel = ZonePanel(self.state)
        self.minimap = Minimap(self.state)
        self.status = StatusBar(self.state)
        self.inspector = Inspector(self.state, self.ctx)
        self.modals = ModalManager(self.state, self.ctx)
        self.loot_editor = LootTableEditor(self.state, self.ctx)
        self.template_editor = TemplateEditor(self.state, self.ctx)

        # Load initial zone (or create blank)
        if self._initial_zone:
            if not self.state.load_zone(self._initial_zone):
                self.state.new_zone(self._initial_zone, 30, 20)
        else:
            zones = list_zones()
            if zones:
                self.state.load_zone(zones[0])
            else:
                self.state.new_zone("untitled", 30, 20)

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
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                continue

            # Full-screen overlays consume events first
            if self.loot_editor.active:
                self.loot_editor.handle_event(event)
                continue
            if self.template_editor.active:
                self.template_editor.handle_event(event)
                continue
            if self.modals.active:
                self.modals.handle_event(event)
                continue

            # Global keyboard shortcuts
            if event.type == pygame.KEYDOWN:
                if self._handle_shortcut(event):
                    continue

            # Menu bar (dropdown menus)
            action = self.menu_bar.handle_event(event)
            if action:
                if action != MenuBar._CONSUMED:
                    self._handle_menu_action(action)
                continue
            # If a dropdown is open, block all mouse events from
            # reaching canvas / palette / etc. beneath it
            if self.menu_bar.is_open:
                if event.type in (pygame.MOUSEBUTTONDOWN,
                                  pygame.MOUSEBUTTONUP,
                                  pygame.MOUSEMOTION):
                    continue

            # Zone navigation bar
            nav_action = self.zone_nav.handle_event(event)
            if nav_action and nav_action.startswith("nav:"):
                zone = nav_action[4:]
                self.state.load_zone(zone)
                self.inspector.force_rebuild()
                continue

            # Left panel (tiles or zones depending on menu bar mode)
            if self.menu_bar.panel_mode == "tiles":
                if self.palette.handle_event(event, self.screen):
                    continue
            elif self.menu_bar.panel_mode == "zones":
                zone_action = self.zone_panel.handle_event(
                    event, self.screen)
                if zone_action and zone_action.startswith("load:"):
                    zname = zone_action[5:]
                    self.state.load_zone(zname)
                    self.inspector.force_rebuild()
                    continue

            # Inspector
            insp_action = self.inspector.handle_event(event, self.screen)
            if insp_action:
                self._handle_inspector_action(insp_action)
                continue

            # Canvas interaction (mouse events on the map area)
            self._handle_canvas_event(event)

    def _handle_shortcut(self, event: pygame.event.Event) -> bool:
        """Global keyboard shortcuts.  Returns True if handled."""
        key = event.key
        mod = event.mod
        st = self.state

        if key == pygame.K_s and mod & pygame.KMOD_CTRL:
            st.save_zone()
            return True
        if key == pygame.K_z and mod & pygame.KMOD_CTRL:
            st.undo()
            self.inspector.force_rebuild()
            return True
        if key == pygame.K_y and mod & pygame.KMOD_CTRL:
            st.redo()
            self.inspector.force_rebuild()
            return True
        if key == pygame.K_g:
            st.show_grid = not st.show_grid
            return True
        if key == pygame.K_m:
            st.show_minimap = not st.show_minimap
            return True
        if key == pygame.K_LEFTBRACKET:
            st.brush_size = max(1, st.brush_size - 1)
            return True
        if key == pygame.K_RIGHTBRACKET:
            st.brush_size = min(9, st.brush_size + 1)
            return True
        if key == pygame.K_f:
            st.first_person = not st.first_person
            st.dirty = True
            st.toast(f"First Person: {'ON' if st.first_person else 'OFF'}")
            return True
        if key == pygame.K_DELETE:
            if 0 <= st.selected_entity < len(st.entities):
                st.delete_entity(st.selected_entity)
                st.selected_entity = -1
                self.inspector.force_rebuild()
                st.toast("Entity deleted")
            return True

        # Number keys → tile shortcut
        if pygame.K_0 <= key <= pygame.K_9 and not mod & pygame.KMOD_CTRL:
            tid = key - pygame.K_0
            from core.tiles import TILE_NAMES
            if tid in TILE_NAMES:
                st.selected_tile = tid
                if st.tool not in (Tool.BRUSH, Tool.FILL):
                    st.tool = Tool.BRUSH
                return True

        return False

    def _handle_menu_action(self, action: str):
        if action == "save":
            self.state.save_zone()
        elif action == "load":
            self.modals.open(ZonePickerModal(self.modals))
        elif action == "new":
            def _on_name(name: str):
                self.state.new_zone(name, 30, 20)
                self.inspector.force_rebuild()
            self.modals.open(
                TextInputModal(self.modals, "New zone name:",
                               "untitled", _on_name))
        elif action == "quit":
            self._running = False
        elif action == "undo":
            self.state.undo()
            self.inspector.force_rebuild()
        elif action == "redo":
            self.state.redo()
            self.inspector.force_rebuild()
        elif action == "delete_entity":
            st = self.state
            if 0 <= st.selected_entity < len(st.entities):
                st.delete_entity(st.selected_entity)
                st.selected_entity = -1
                self.inspector.force_rebuild()
                st.toast("Entity deleted")
        elif action == "loot":
            self.loot_editor.open()
        elif action == "templates":
            self.template_editor.open()

    def _handle_inspector_action(self, action: str):
        st = self.state
        if action == "delete_entity":
            if 0 <= st.selected_entity < len(st.entities):
                st.delete_entity(st.selected_entity)
                st.selected_entity = -1
                self.inspector.force_rebuild()
                st.toast("Entity deleted")
        elif action == "add_component":
            if 0 <= st.selected_entity < len(st.entities):
                self.modals.open(AddComponentModal(self.modals))
        elif action.startswith("select_entity:"):
            idx = int(action.split(":")[1])
            st.selected_entity = idx
            st.tool = Tool.ENTITY
            self.inspector.force_rebuild()

    # ── Canvas interaction ──────────────────────────────────────

    def _handle_canvas_event(self, event: pygame.event.Event):
        st = self.state
        vp = self.canvas.viewport_rect(self.screen)

        # Mouse motion → hover + pan + drag
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            if vp.collidepoint(mx, my):
                st.hover_tile = self.canvas.screen_to_tile(mx, my, self.screen)
            else:
                st.hover_tile = None

            # Pan
            if st._panning:
                dx = mx - st._pan_start[0]
                dy = my - st._pan_start[1]
                st.cam_x = st._cam_start[0] + dx / st.zoom
                st.cam_y = st._cam_start[1] + dy / st.zoom

            # Entity drag
            if st.entity_dragging and st.hover_tile:
                idx = st.selected_entity
                if 0 <= idx < len(st.entities):
                    r, c = st.hover_tile
                    ent = st.entities[idx]
                    pos = ent.setdefault("position", {})
                    pos["x"] = float(c) + 0.5
                    pos["y"] = float(r) + 0.5
                    st.dirty = True

            # Paint while dragging
            if (event.buttons[0] and st.hover_tile
                    and not st._panning and not st.entity_dragging):
                if st.tool == Tool.BRUSH:
                    r, c = st.hover_tile
                    st.paint(r, c)
                    st.dirty = True
                elif st.tool == Tool.ERASER:
                    r, c = st.hover_tile
                    st.erase(r, c)
                    st.dirty = True

        # Zoom
        if event.type == pygame.MOUSEWHEEL and vp.collidepoint(*pygame.mouse.get_pos()):
            if event.y > 0:
                st.zoom = min(6.0, st.zoom * 1.15)
            elif event.y < 0:
                st.zoom = max(0.15, st.zoom / 1.15)

        # Mouse button down
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            if not vp.collidepoint(mx, my):
                return

            # Middle mouse → pan
            if event.button == 2:
                st._panning = True
                st._pan_start = (mx, my)
                st._cam_start = (st.cam_x, st.cam_y)
                return

            if event.button != 1:
                return

            tile = self.canvas.screen_to_tile(mx, my, self.screen)
            if tile is None:
                return
            r, c = tile

            tool = st.tool

            if tool == Tool.BRUSH:
                st.push_undo()
                st.paint(r, c)
                st.dirty = True

            elif tool == Tool.ERASER:
                st.push_undo()
                st.erase(r, c)
                st.dirty = True

            elif tool == Tool.FILL:
                st.push_undo()
                st.flood_fill(r, c)
                st.dirty = True

            elif tool == Tool.PICKER:
                if 0 <= r < st.map_h and 0 <= c < st.map_w:
                    st.selected_tile = st.tiles[r][c]
                    st.tool = Tool.BRUSH
                    st.toast(f"Picked tile {st.selected_tile}")

            elif tool == Tool.ENTITY:
                eidx = st.entity_at(r, c)
                if eidx >= 0:
                    st.selected_entity = eidx
                    st.entity_dragging = True
                    self.inspector.force_rebuild()
                else:
                    # Open prefab picker
                    self.modals.open(
                        PrefabPickerModal(self.modals, (r, c)))

            elif tool == Tool.PORTAL:
                # Check existing
                for p in st.portals:
                    if [r, c] in p["tiles"]:
                        # Edit existing portal
                        self.modals.open(
                            PortalWizardModal(self.modals, (r, c),
                                             editing=p))
                        return
                # New portal
                st.tiles[r][c] = 9  # portal tile
                self.modals.open(
                    PortalWizardModal(self.modals, (r, c)))

            elif tool == Tool.ANCHOR:
                st.anchor = (float(c) + 0.5, float(r) + 0.5)
                st.push_undo()
                st.toast(f"Anchor set to ({c}, {r})")

        # Mouse button up
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                st._panning = False
            if event.button == 1:
                if st.entity_dragging:
                    st.entity_dragging = False
                    st.push_undo()
                    self.inspector.force_rebuild()
                # Push undo after paint stroke
                if st.tool in (Tool.BRUSH, Tool.ERASER) and st.dirty:
                    st.push_undo()

        # Right-click → delete portal or deselect
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            mx, my = event.pos
            if vp.collidepoint(mx, my):
                tile = self.canvas.screen_to_tile(mx, my, self.screen)
                if tile:
                    r, c = tile
                    if st.tool == Tool.PORTAL:
                        st.delete_portal_at(r, c)
                    elif st.tool == Tool.ENTITY:
                        st.selected_entity = -1
                        self.inspector.force_rebuild()

    # ── Update ──────────────────────────────────────────────────

    def _update(self, dt: float):
        st = self.state
        if st.toast_timer > 0:
            st.toast_timer -= dt

    # ── Draw ────────────────────────────────────────────────────

    def _draw(self, dt: float):
        screen = self.screen

        # Full-screen overlays
        if self.loot_editor.active:
            self.loot_editor.draw(screen, self.font, self.font_sm, dt)
            return
        if self.template_editor.active:
            self.template_editor.draw(screen, self.font, self.font_sm, dt)
            return

        # Recompute responsive layout for current window size
        Layout.update(*screen.get_size())

        screen.fill(Theme.BG)

        # Canvas (map)
        self.canvas.draw(screen, self.font, self.font_sm)

        # Panels
        self.zone_nav.draw(screen, self.font_sm)

        # Left panel (content depends on menu bar mode)
        if self.menu_bar.panel_mode == "tiles":
            self.palette.draw(screen, self.font, self.font_sm)
        elif self.menu_bar.panel_mode == "zones":
            self.zone_panel.draw(screen, self.font, self.font_sm)

        self.minimap.draw(screen, self.font_sm)
        self.status.draw(screen, self.font_sm)

        # Inspector
        self.inspector.draw(screen, self.font, self.font_sm, dt)

        # Menu bar drawn last so dropdowns overlap everything
        self.menu_bar.draw(screen, self.font, self.font_sm)

        # Modals on top
        if self.modals.active:
            self.modals.draw(screen, self.font, self.font_sm, dt)
