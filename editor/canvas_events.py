"""editor/canvas_events.py — Canvas interaction handling for the editor.

Provides ``CanvasEventsMixin``, mixed into ``EditorApp`` so the
canvas mouse/keyboard logic lives in its own module.
"""

from __future__ import annotations

import pygame

from editor.state import Tool
from editor.entity_factory import create_forge_entity


class CanvasEventsMixin:
    """Canvas interaction, entity placement, FP helpers, and exports."""

    # ── FP Preview / Edit helpers ───────────────────────────────

    def _do_fp_preview(self):
        """Toggle the FP preview PIP on/off."""
        st = self.state
        self.fp_preview.toggle()
        if self.fp_preview.active:
            st = self.state
            self.fp_preview.sync_to_anchor((st.map_w / 2.0, st.map_h / 2.0))
        msg = ("FP Preview ON (Tab=Edit, F=Fullscreen)"
               if self.fp_preview.active else "FP Preview OFF")
        st.toast(msg)

    def _do_fp_edit(self):
        """Jump straight into fullscreen FP editing mode."""
        st = self.state
        if not self.fp_preview.active:
            self.fp_preview.toggle()
            st = self.state
            self.fp_preview.sync_to_anchor((st.map_w / 2.0, st.map_h / 2.0))
        if not self.fp_preview.fullscreen:
            self.fp_preview.toggle_fullscreen()
        st.toast("FP Edit Mode \u2014 LClick=Paint  RClick=Pick  Esc=Exit")

    # ── Canvas interaction ──────────────────────────────────────

    def _handle_canvas_event(self, event: pygame.event.Event):
        st = self.state
        vp = self.canvas.viewport_rect(self.screen)

        # Mouse motion → hover + pan + drag
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            if vp.collidepoint(mx, my):
                st.hover_tile = self.canvas.screen_to_tile(
                    mx, my, self.screen)
            else:
                st.hover_tile = None

            # Pan
            if st._panning:
                dx = mx - st._pan_start[0]
                dy = my - st._pan_start[1]
                st.cam_x = st._cam_start[0] + dx / st.zoom
                st.cam_y = st._cam_start[1] + dy / st.zoom

            # Entity drag (while in select mode with entity selected)
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
        if (event.type == pygame.MOUSEWHEEL
                and vp.collidepoint(*pygame.mouse.get_pos())):
            if event.y > 0:
                st.zoom = min(6.0, st.zoom * 1.15)
            elif event.y < 0:
                st.zoom = max(0.15, st.zoom / 1.15)

        # Mouse button down
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            if not vp.collidepoint(mx, my):
                return

            # Middle-click → pan start
            if event.button == 2:
                st._panning = True
                st._pan_start = (mx, my)
                st._cam_start = (st.cam_x, st.cam_y)
                return

            if event.button == 1:
                tile = self.canvas.screen_to_tile(mx, my, self.screen)
                if not tile:
                    return
                r, c = tile
                tool = st.tool

                if tool == Tool.SELECT:
                    # Entity placement from pending prefab
                    if st.pending_prefab:
                        self._place_pending_entity(r, c)
                        return
                    # Check for entity under cursor
                    eidx = st.entity_at(r, c)
                    if eidx >= 0:
                        st.selected_entity = eidx
                        st.entity_dragging = True
                        self.inspector.set_tab("entity")
                        self.inspector.force_rebuild()
                    else:
                        # Deselect entity, select tile for inspection
                        st.selected_entity = -1
                        if 0 <= r < st.map_h and 0 <= c < st.map_w:
                            st.selected_tile = st.tiles[r][c]
                            self.inspector.set_tab("tile")
                        self.inspector.force_rebuild()

                elif tool == Tool.BRUSH:
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

        # Mouse button up
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                st._panning = False
            if event.button == 1:
                if st.entity_dragging:
                    st.entity_dragging = False
                    st.push_undo()
                    self.inspector.force_rebuild()

        # Right-click → deselect entity
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            mx, my = event.pos
            if vp.collidepoint(mx, my):
                if st.selected_entity >= 0:
                    st.selected_entity = -1
                    self.inspector.force_rebuild()
                elif st.pending_prefab:
                    st.pending_prefab = ""
                    st.toast("Placement cancelled")

    # ── Entity placement from pending_prefab ───────────────────

    def _place_pending_entity(self, row: int, col: int):
        """Place the entity selected via the EntityPanel sidebar."""
        st = self.state
        name = st.pending_prefab
        if not name:
            return

        if name.startswith("forge:"):
            aid = name[6:]
            self._place_forge_entity(row, col, aid)
        else:
            from editor.canvas import get_prefab_defaults
            from editor.entity_factory import create_prefab_entity
            defaults = get_prefab_defaults()
            ent = create_prefab_entity(name, defaults, row, col, st.entities)
            st.entities.append(ent)
            st.selected_entity = len(st.entities) - 1
            self.inspector.set_tab("entity")
            st.push_undo()
            self.inspector.force_rebuild()
            st.toast(f"Placed {name}: {ent.id}")

    # ── Forge placement helpers ─────────────────────────────────

    def _begin_forge_placement(self):
        """Start placing the Forge's selected archetype on the map."""
        aid = self.forge.selected_id
        if not aid:
            self.state.toast("No archetype selected")
            return
        self.state.pending_prefab = f"forge:{aid}"
        self.forge.close()
        self.state.tool = Tool.SELECT
        self.state.toast(f"Click map to place '{aid}' \u2014 Esc/RClick cancel")

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
        self.menu_bar.panel_mode = "entities"
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
