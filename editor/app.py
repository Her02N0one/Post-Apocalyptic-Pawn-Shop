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
from editor.panels import (
    MenuBar, TilePalette, ZonePanel, EntityPanel,
    TextureBrowserPanel, PortalPanel, RoomTemplatePanel,
    Minimap, StatusBar, ZoneNav, PanelSplitter,
)
from editor.inspector import Inspector
from editor.modals import (
    ModalManager, TextInputModal, ZonePickerModal,
    PrefabPickerModal, AddComponentModal, PortalWizardModal,
    TileEditorModal,
)
from editor.loot_editor import LootTableEditor
from editor.templates import TemplateEditor
from editor.entity_forge import EntityForgeModal
from editor.fp_preview import FPPreview
from editor.layout import Layout
from editor.entity_factory import create_forge_entity
from systems.textures import TextureAtlas, browse_and_import

# Valid panel mode identifiers
_PANEL_MODES = frozenset(
    {"tiles", "entities", "textures", "portals", "templates", "zones"}
)


# ═════════════════════════════════════════════════════════════════════

class EditorApp:
    """Self-contained Pygame application for the map editor."""

    TITLE = "Post-Apocalyptic Pawn Shop — Map Editor"
    MIN_W, MIN_H = 960, 640
    FPS = 60

    def __init__(self, zone_name: str = ""):
        self._initial_zone = zone_name
        self._running = False
        self._pending_forge_id: str | None = None  # Forge placement mode

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

        # Table-driven left panel lookup (panel_mode → widget)
        self._panel_widgets: dict[str, object] = {
            "tiles":     self.palette,
            "zones":     self.zone_panel,
            "entities":  self.entity_panel,
            "textures":  self.texture_panel,
            "portals":   self.portal_panel,
            "templates": self.template_panel,
        }

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

    def _build_fonts(self):
        """(Re)create fonts at sizes appropriate for the current scale."""
        s = Layout.scale
        self.font = pygame.font.SysFont("monospace", max(12, round(16 * s)))
        self.font_sm = pygame.font.SysFont("monospace", max(10, round(12 * s)))
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

            # Full-screen overlays consume events first
            if self.forge.active:
                result = self.forge.handle_event(event)
                if result == "place":
                    self._begin_forge_placement()
                continue
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
                    self._dispatch_action(action)
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
                self._do_load_zone(nav_action[4:])
                continue

            # Panel splitter drag handles (before palette/inspector)
            if self.splitter.handle_event(event):
                continue

            # FP fullscreen consumes ALL events (before palette/inspector)
            if self.fp_preview.active and self.fp_preview.fullscreen:
                if self.fp_preview.handle_event(event, self.state):
                    continue

            # Left panel — dispatch via _panel_handlers table
            panel_result = self._handle_left_panel_event(event)
            if panel_result is not None:
                continue

            # Inspector
            insp_action = self.inspector.handle_event(event, self.screen)
            if insp_action:
                self._dispatch_action(insp_action)
                continue

            # Canvas interaction (mouse events on the map area)
            # FP PIP-mode consumes WASD/arrow keys when active
            if self.fp_preview.active:
                if self.fp_preview.handle_event(event, self.state):
                    continue
            self._handle_canvas_event(event)

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
        if key == pygame.K_ESCAPE and self._pending_forge_id:
            self._pending_forge_id = None
            st.toast("Placement cancelled")
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

    def _dispatch_action(self, action: str):
        """Route any action string from menus, inspector, or modals.

        Uses a dispatch table for exact-match actions and a prefix
        table for parameterised ``prefix:value`` actions so new
        actions can be added in one place.
        """
        # ── exact-match table ───────────────────────────────────
        handler = self._ACTION_TABLE.get(action)
        if handler is not None:
            handler(self)
            return

        # ── prefix:value actions ────────────────────────────────
        if ":" in action:
            prefix, value = action.split(":", 1)
            prefix_handler = self._PREFIX_TABLE.get(prefix)
            if prefix_handler is not None:
                prefix_handler(self, value)

    # ── Action handlers (exact match) ───────────────────────────

    def _act_save(self):
        self.state.save_zone()

    def _act_quit(self):
        self._running = False

    def _act_load(self):
        self.modals.open(ZonePickerModal(self.modals))

    def _act_new(self):
        def _on_name(name: str):
            self.state.new_zone(name, 30, 20)
            self.inspector.force_rebuild()
        self.modals.open(
            TextInputModal(self.modals, "New zone name:",
                           "untitled", _on_name))

    def _act_loot(self):
        self.loot_editor.open()

    def _act_templates(self):
        self.template_editor.open()

    def _act_forge(self):
        self.forge.open()

    def _act_export_mpz(self):
        self._export_current_mpz()

    def _act_export_all_mpz(self):
        self._export_all_mpz()

    def _act_import_texture(self):
        dest = browse_and_import()
        if dest:
            from core.tiles import TILE_REGISTRY as _reg
            key = dest.stem
            for td in _reg.values():
                tk = td.texture_key or td.id
                if tk == key:
                    self.atlas.invalidate(td.id)
            self.state.toast(f"Imported texture: {dest.name}")

    def _act_add_component(self):
        st = self.state
        if 0 <= st.selected_entity < len(st.entities):
            self.modals.open(AddComponentModal(self.modals))

    def _act_toggle_grid(self):
        self.state.show_grid = not self.state.show_grid

    def _act_toggle_minimap(self):
        self.state.show_minimap = not self.state.show_minimap

    def _act_fp_preview(self):
        self._do_fp_preview()

    def _act_fp_edit(self):
        self._do_fp_edit()

    def _act_brush_inc(self):
        self.state.brush_size = min(9, self.state.brush_size + 1)

    def _act_brush_dec(self):
        self.state.brush_size = max(1, self.state.brush_size - 1)

    _ACTION_TABLE: dict[str, callable] = {
        "save":            _act_save,
        "quit":            _act_quit,
        "undo":            lambda self: self._do_undo(),
        "redo":            lambda self: self._do_redo(),
        "delete_entity":   lambda self: self._do_delete_entity(),
        "load":            _act_load,
        "new":             _act_new,
        "loot":            _act_loot,
        "templates":       _act_templates,
        "forge":           _act_forge,
        "export_mpz":      _act_export_mpz,
        "export_all_mpz":  _act_export_all_mpz,
        "import_texture":  _act_import_texture,
        "add_component":   _act_add_component,
        "toggle_grid":     _act_toggle_grid,
        "toggle_minimap":  _act_toggle_minimap,
        "fp_preview":      _act_fp_preview,
        "fp_edit":         _act_fp_edit,
        "brush_inc":       _act_brush_inc,
        "brush_dec":       _act_brush_dec,
    }

    # ── Action handlers (prefix:value) ──────────────────────────

    def _pfx_select_entity(self, value: str):
        try:
            idx = int(value)
        except ValueError:
            return
        self.state.selected_entity = idx
        self.state.tool = Tool.ENTITY
        self.inspector.force_rebuild()

    def _pfx_panel(self, mode: str):
        if mode in _PANEL_MODES:
            self.menu_bar.panel_mode = mode

    def _pfx_copy_tex(self, key: str):
        self.state.toast(f"Texture key: {key}")

    def _pfx_select_portal(self, value: str):
        try:
            idx = int(value)
        except ValueError:
            return
        st = self.state
        if 0 <= idx < len(st.portals):
            tiles = st.portals[idx].get("tiles", [])
            if tiles and len(tiles[0]) >= 2:
                r, c = tiles[0][0], tiles[0][1]
                st.hover_tile = (r, c)
            dest = st.portals[idx].get("target_zone",
                                       st.portals[idx].get("dest_zone", "?"))
            st.toast(f"Portal #{idx} → {dest}")

    def _pfx_select_template(self, fname: str):
        self.state.toast(f"Template: {fname} (stamp placement TBD)")

    def _pfx_select_prefab(self, name: str):
        self.state.pending_prefab = name
        self.state.tool = Tool.ENTITY
        self.state.toast(f"Prefab: {name} — click canvas to place")

    def _pfx_select_forge(self, fid: str):
        self.state.pending_prefab = f"forge:{fid}"
        self.state.tool = Tool.ENTITY
        self.state.toast(f"Forge: {fid} — click canvas to place")

    def _pfx_tool(self, tool_name: str):
        st = self.state
        if hasattr(Tool, tool_name.upper()):
            st.tool = getattr(Tool, tool_name.upper())
        else:
            st.tool = tool_name
        # Auto-switch left panel to match tool
        if st.tool in (Tool.BRUSH, Tool.FILL, Tool.ERASER):
            self.menu_bar.panel_mode = "tiles"
        elif st.tool == Tool.ENTITY:
            self.menu_bar.panel_mode = "entities"

    _PREFIX_TABLE: dict[str, callable] = {
        "select_entity":   _pfx_select_entity,
        "panel":           _pfx_panel,
        "copy_tex":        _pfx_copy_tex,
        "select_portal":   _pfx_select_portal,
        "select_template": _pfx_select_template,
        "select_prefab":   _pfx_select_prefab,
        "select_forge":    _pfx_select_forge,
        "tool":            _pfx_tool,
    }

    # ── FP Preview / Edit helpers ───────────────────────────────

    def _do_fp_preview(self):
        """Toggle the FP preview PIP on/off."""
        st = self.state
        self.fp_preview.toggle()
        if self.fp_preview.active:
            self.fp_preview.sync_to_anchor(st.anchor)
        msg = "FP Preview ON (Tab=Edit, F=Fullscreen)" if self.fp_preview.active else "FP Preview OFF"
        st.toast(msg)

    def _do_fp_edit(self):
        """Jump straight into fullscreen FP editing mode."""
        st = self.state
        if not self.fp_preview.active:
            self.fp_preview.toggle()  # activate PIP first
            self.fp_preview.sync_to_anchor(st.anchor)
        if not self.fp_preview.fullscreen:
            self.fp_preview.toggle_fullscreen()  # enter fullscreen
        st.toast("FP Edit Mode — LClick=Paint  RClick=Pick  Esc=Exit")

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
                    ent.position.x = float(c) + 0.5
                    ent.position.y = float(r) + 0.5
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

            # Forge placement mode
            if self._pending_forge_id:
                self._place_forge_entity(r, c, self._pending_forge_id)
                self._pending_forge_id = None
                return

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
                st.tiles[r][c] = "door"  # portal tile
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

    # ── Forge placement helpers ─────────────────────────────────

    def _begin_forge_placement(self):
        """Start placing the Forge's selected archetype on the map."""
        aid = self.forge.selected_id
        if not aid:
            self.state.toast("No archetype selected")
            return
        self._pending_forge_id = aid
        self.forge.close()
        self.state.tool = Tool.ENTITY
        self.state.toast(f"Click map to place '{aid}' — Esc to cancel")

    def _place_forge_entity(self, row: int, col: int, archetype_id: str):
        """Create an entity from a Forge archetype at the given tile."""
        from editor.forge_registry import ForgeRegistry
        reg = ForgeRegistry.instance()
        arch = reg.get(archetype_id)
        if arch is None:
            self.state.toast(f"Archetype '{archetype_id}' not found")
            return

        st = self.state
        ent = create_forge_entity(arch, row, col, st.entities)
        st.entities.append(ent)
        st.selected_entity = len(st.entities) - 1
        st.push_undo()
        self.inspector.force_rebuild()
        st.toast(f"Placed {arch.display_name or arch.id}")

    # ── MessagePack export helpers ─────────────────────────────

    def _export_current_mpz(self):
        """Export the current zone to .mpz."""
        from editor.msgpack_io import export_zone_file
        st = self.state
        if not st.zone_name:
            st.toast("No zone to export")
            return
        # Save JSON first so export picks up latest changes
        st.save_zone()
        out = export_zone_file(st.zone_name)
        if out:
            st.toast(f"Exported: {out.name}")
        else:
            st.toast("Export failed")

    def _export_all_mpz(self):
        """Export every JSON zone to .mpz."""
        from editor.msgpack_io import export_all_zones
        results = export_all_zones()
        self.state.toast(f"Exported {len(results)} zones to .mpz")

    # ── Update ──────────────────────────────────────────────────

    def _update(self, dt: float):
        st = self.state
        if st.toast_timer > 0:
            st.toast_timer -= dt
        # Update FP preview camera movement
        if self.fp_preview.active:
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

        # Canvas (map)
        self.canvas.draw(screen, self.font, self.font_sm)

        # Panels
        self.zone_nav.draw(screen, self.font_sm)

        # Left panel (content depends on menu bar mode)
        panel_widget = self._panel_widgets.get(self.menu_bar.panel_mode)
        if panel_widget is not None:
            panel_widget.draw(screen, self.font, self.font_sm)

        self.minimap.draw(screen, self.font_sm)
        self.status.draw(screen, self.font_sm)

        # Inspector
        self.inspector.draw(screen, self.font, self.font_sm, dt)

        # Pending forge placement indicator
        if self._pending_forge_id:
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
                entities=self.state.entities)

        # Panel splitter handles (drawn over panel borders)
        self.splitter.draw(screen)

        # Menu bar drawn last so dropdowns overlap everything
        self.menu_bar.draw(screen, self.font, self.font_sm)

        # Modals on top
        if self.modals.active:
            self.modals.draw(screen, self.font, self.font_sm, dt)

    def _draw_placement_hint(self, screen: pygame.Surface):
        """Draw a small banner when forge placement is pending."""
        L = Layout
        hint = f"Placing: {self._pending_forge_id}  |  Click map \u00b7 Esc cancel"
        hw = self.font_sm.size(hint)[0] + 20
        hx = L.canvas_x + (L.canvas_w - hw) // 2
        hy = L.canvas_y + 4
        bg = pygame.Surface((hw, 22), pygame.SRCALPHA)
        bg.fill((40, 80, 40, 200))
        screen.blit(bg, (hx, hy))
        from editor.ui import draw_text
        draw_text(screen, hint, hx + 10, hy + 4, Theme.SUCCESS, self.font_sm)