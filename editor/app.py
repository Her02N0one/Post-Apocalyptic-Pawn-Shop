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
    Minimap, StatusBar, ZoneNav,
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
from systems.textures import TextureAtlas, browse_and_import


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

            # FP fullscreen consumes ALL events (before palette/inspector)
            if self.fp_preview.active and self.fp_preview.fullscreen:
                if self.fp_preview.handle_event(event, self.state):
                    continue

            # Left panel (tiles or zones)
            if self.menu_bar.panel_mode == "tiles":
                pal_result = self.palette.handle_event(event, self.screen)
                if pal_result == "add_tile":
                    self.modals.open(TileEditorModal(
                        self.modals, atlas=self.atlas))
                    continue
                elif pal_result and pal_result.startswith("edit_tile:"):
                    from core.tiles import TILE_REGISTRY
                    tid = pal_result.split(":", 1)[1]
                    td = TILE_REGISTRY.get(tid)
                    if td:
                        self.modals.open(TileEditorModal(
                            self.modals, edit_tile=td, atlas=self.atlas))
                    continue
                elif pal_result:
                    continue
            elif self.menu_bar.panel_mode == "zones":
                zone_action = self.zone_panel.handle_event(
                    event, self.screen)
                if zone_action and zone_action.startswith("load:"):
                    self._do_load_zone(zone_action[5:])
                    continue
            elif self.menu_bar.panel_mode == "entities":
                ent_action = self.entity_panel.handle_event(
                    event, self.screen)
                if ent_action:
                    self._dispatch_action(ent_action)
                    continue
            elif self.menu_bar.panel_mode == "textures":
                tex_action = self.texture_panel.handle_event(
                    event, self.screen)
                if tex_action:
                    self._dispatch_action(tex_action)
                    continue
            elif self.menu_bar.panel_mode == "portals":
                port_action = self.portal_panel.handle_event(
                    event, self.screen)
                if port_action:
                    self._dispatch_action(port_action)
                    continue
            elif self.menu_bar.panel_mode == "templates":
                tmpl_action = self.template_panel.handle_event(
                    event, self.screen)
                if tmpl_action:
                    self._dispatch_action(tmpl_action)
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
        """Route any action string from menus, inspector, or modals."""
        st = self.state

        if action == "save":
            st.save_zone()
        elif action == "quit":
            self._running = False
        elif action == "undo":
            self._do_undo()
        elif action == "redo":
            self._do_redo()
        elif action == "delete_entity":
            self._do_delete_entity()
        elif action == "load":
            self.modals.open(ZonePickerModal(self.modals))
        elif action == "new":
            def _on_name(name: str):
                st.new_zone(name, 30, 20)
                self.inspector.force_rebuild()
            self.modals.open(
                TextInputModal(self.modals, "New zone name:",
                               "untitled", _on_name))
        elif action == "loot":
            self.loot_editor.open()
        elif action == "templates":
            self.template_editor.open()
        elif action == "forge":
            self.forge.open()
        elif action == "export_mpz":
            self._export_current_mpz()
        elif action == "export_all_mpz":
            self._export_all_mpz()
        elif action == "import_texture":
            dest = browse_and_import()
            if dest:
                # Invalidate any cached tile that uses this texture key
                from core.tiles import TILE_REGISTRY as _reg
                key = dest.stem
                for td in _reg.values():
                    tk = td.texture_key or td.id
                    if tk == key:
                        self.atlas.invalidate(td.id)
                st.toast(f"Imported texture: {dest.name}")
            # else: user cancelled — no-op
        elif action == "add_component":
            if 0 <= st.selected_entity < len(st.entities):
                self.modals.open(AddComponentModal(self.modals))
        elif action.startswith("select_entity:"):
            idx = int(action.split(":")[1])
            st.selected_entity = idx
            st.tool = Tool.ENTITY
            self.inspector.force_rebuild()
        # View menu actions
        elif action == "toggle_grid":
            st.show_grid = not st.show_grid
        elif action == "toggle_minimap":
            st.show_minimap = not st.show_minimap
        elif action == "fp_preview":
            self._do_fp_preview()
        elif action == "fp_edit":
            self._do_fp_edit()
        elif action == "brush_inc":
            st.brush_size = min(9, st.brush_size + 1)
        elif action == "brush_dec":
            st.brush_size = max(1, st.brush_size - 1)
        elif action == "panel:tiles":
            self.menu_bar.panel_mode = "tiles"
        elif action == "panel:zones":
            self.menu_bar.panel_mode = "zones"
        elif action == "panel:entities":
            self.menu_bar.panel_mode = "entities"
        elif action == "panel:textures":
            self.menu_bar.panel_mode = "textures"
        elif action == "panel:portals":
            self.menu_bar.panel_mode = "portals"
        elif action == "panel:templates":
            self.menu_bar.panel_mode = "templates"
        # Texture browser
        elif action.startswith("copy_tex:"):
            key = action.split(":", 1)[1]
            st.toast(f"Texture key: {key}")
        # Portal selection
        elif action.startswith("select_portal:"):
            idx = int(action.split(":", 1)[1])
            if 0 <= idx < len(st.portals):
                tiles = st.portals[idx].get("tiles", [])
                if tiles:
                    r, c = tiles[0]
                    st.hover_tile = (r, c)
                st.toast(f"Portal #{idx} → {st.portals[idx].get('dest_zone', '?')}")
        # Template selection
        elif action.startswith("select_template:"):
            fname = action.split(":", 1)[1]
            st.toast(f"Template: {fname} (stamp placement TBD)")
        # Entity preset selection
        elif action.startswith("select_prefab:"):
            name = action.split(":", 1)[1]
            st.pending_prefab = name
            st.tool = Tool.ENTITY
            st.toast(f"Prefab: {name} — click canvas to place")
        elif action.startswith("select_forge:"):
            fid = action.split(":", 1)[1]
            st.pending_prefab = f"forge:{fid}"
            st.tool = Tool.ENTITY
            st.toast(f"Forge: {fid} — click canvas to place")
        # Tool actions
        elif action.startswith("tool:"):
            tool_name = action.split(":", 1)[1]
            try:
                st.tool = Tool(tool_name)
            except ValueError:
                pass
            # Auto-switch left panel to match tool
            if st.tool in (Tool.BRUSH, Tool.FILL, Tool.ERASER):
                self.menu_bar.panel_mode = "tiles"
            elif st.tool == Tool.ENTITY:
                self.menu_bar.panel_mode = "entities"

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
        existing_ids = {e.get("id", "") for e in st.entities}
        base = f"{arch.id}_{len(st.entities)}"
        uid = base
        n = 0
        while uid in existing_ids:
            n += 1
            uid = f"{arch.id}_{n}"

        ent: dict = {
            "id": uid,
            "forge_archetype": arch.id,
            "position": {"x": float(col) + 0.5, "y": float(row) + 0.5},
            "identity": {
                "name": arch.display_name or arch.id.replace("_", " ").title(),
                "kind": arch.kind,
            },
            "sprite": {
                "char": arch.sprite_char if arch.kind == "billboard" else (
                    "\u25A3" if arch.kind == "tile" else "\u25A1"),
                "color": list(arch.sprite_color if arch.kind == "billboard"
                              else arch.color),
                "layer": 5,
            },
        }
        if arch.dev_notes:
            ent["dev_notes"] = arch.dev_notes
        if arch.tags:
            ent["tags"] = list(arch.tags)

        # Kind-specific components
        if arch.kind == "tile":
            ent["tile_entity"] = {"tile_type": "container",
                                  "tiles": [[row, col]]}
            if arch.texture_key:
                ent["wall_sprite"] = {
                    "texture_key": arch.texture_key,
                    "width": 1.0,
                    "height": arch.ceiling_z - arch.floor_z,
                    "elevation": arch.floor_z,
                }
        elif arch.kind == "box":
            if arch.solid:
                ent["collider"] = {"w": arch.width, "h": arch.depth,
                                   "solid": True}
            if arch.texture_key:
                ent["wall_sprite"] = {
                    "texture_key": arch.texture_key,
                    "width": arch.width,
                    "height": arch.height,
                    "elevation": arch.z_offset,
                }
        elif arch.kind == "billboard":
            if arch.solid:
                ent["collider"] = {"w": 0.4, "h": 0.4, "solid": True}

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

    # ── Draw ────────────────────────────────────────────────────

    def _draw(self, dt: float):
        screen = self.screen

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
        elif self.menu_bar.panel_mode == "entities":
            self.entity_panel.draw(screen, self.font, self.font_sm)
        elif self.menu_bar.panel_mode == "textures":
            self.texture_panel.draw(screen, self.font, self.font_sm)
        elif self.menu_bar.panel_mode == "portals":
            self.portal_panel.draw(screen, self.font, self.font_sm)
        elif self.menu_bar.panel_mode == "templates":
            self.template_panel.draw(screen, self.font, self.font_sm)

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
                selected_tile=self.state.selected_tile)

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