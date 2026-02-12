"""scenes/editor_controller.py — Tile-editor state and logic.

Extracted from WorldScene to keep the gameplay scene under control.
The controller holds all editor-specific state (brush, teleporter
placement, text input) and exposes three entry-points that WorldScene
delegates to:

    handle_event(event, app, scene)  — raw KEYDOWN / MOUSE events
    update(dt, app, scene, input_mgr) — intent-driven logic each frame
    draw(surface, app, scene, cam, ox, oy, start_row, start_col,
         end_row, end_col)           — overlay rendering
"""

from __future__ import annotations
import pygame
from core.zone import (
    ZONE_MAPS, ZONE_ANCHORS, ZONE_TELEPORTERS,
    ZONE_PORTALS, _PORTAL_LOOKUP,
    Portal, PortalSide,
    get_portal_for_tile, get_portal_sides,
    save_portals, portal_lookup_for_zone,
)
from core.constants import TILE_SIZE, TILE_COLORS

try:
    from core.nbt import save_zone_nbt
except Exception:
    save_zone_nbt = None


class EditorController:
    """Encapsulates the entire tile-editor UI that WorldScene toggles with F4."""

    def __init__(self):
        self.selected_tile = 1
        self.brush_size = 1
        self.mouse_drag_start = None
        self.teleporters: dict = {}
        self.teleporter_mode = False
        self.tp_move_mode = False
        self._moving_tp = None
        self._pending_tp = None  # (row, col) waiting for destination text
        self.text_input_active = False
        self.text_input_buffer = ""
        self.input_target: str | None = None

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def screen_to_tile(mx: int, my: int, cam, screen_size, map_w, map_h):
        """Convert mouse screen coords → (row, col) or None."""
        sw, sh = screen_size
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < map_h and 0 <= col < map_w:
            return row, col
        return None

    @staticmethod
    def parse_tp_value(val: str):
        """Parse 'zone:row,col' → dict or None."""
        val = val.strip()
        if ":" in val and "," in val:
            try:
                z, rc = val.split(":", 1)
                rs, cs = rc.split(",", 1)
                return {"zone": z.strip(), "r": int(rs), "c": int(cs)}
            except Exception:
                return None
        return None

    def paint_at(self, tiles, row, col, map_h, map_w):
        """Paint a square of brush_size centred at (row, col)."""
        half = self.brush_size // 2
        for rr in range(row - half, row - half + self.brush_size):
            for cc in range(col - half, col - half + self.brush_size):
                if 0 <= rr < map_h and 0 <= cc < map_w:
                    tiles[rr][cc] = self.selected_tile

    def save_zone(self, zone, tiles):
        """Persist tiles + portals (TOML) and legacy TPs (NBT)."""
        ZONE_MAPS[zone] = [row[:] for row in tiles]

        # ── Save portals to data/portals.toml ────────────────────────
        if ZONE_PORTALS:
            try:
                save_portals()
            except Exception as ex:
                print(f"[PORTAL] save failed: {ex}")

        # ── Save non-portal teleporters to NBT ──────────────────────
        legacy_tps: dict = {}
        for rc, tgt in self.teleporters.items():
            if isinstance(tgt, dict) and tgt.get("portal_id"):
                continue      # managed by portals.toml
            legacy_tps[rc] = tgt
        ZONE_TELEPORTERS[zone] = legacy_tps

        if save_zone_nbt:
            try:
                anchor_val = ZONE_ANCHORS.get(zone)
                p = save_zone_nbt(zone, tiles, anchor=anchor_val,
                                  teleporters=legacy_tps)
                print(f"[ZONE] saved {p}")
            except Exception as ex:
                print(f"[ZONE] save failed: {ex}")
        else:
            print("[ZONE] saved in memory (install nbtlib for .nbt export)")

    # ── event handling ──────────────────────────────────────────────

    def handle_key(self, event, scene):
        """Handle a KEYDOWN while text input is active.  Returns True
        if the event was consumed."""
        if not self.text_input_active:
            return False

        if event.key == pygame.K_RETURN:
            val = self.text_input_buffer.strip()
            self._commit_text_input(val, scene)
            return True
        elif event.key == pygame.K_ESCAPE:
            self.text_input_active = False
            self.text_input_buffer = ""
            self.input_target = None
            self._pending_tp = None
            print("[EDITOR] input cancelled")
            return True
        elif event.key == pygame.K_BACKSPACE:
            self.text_input_buffer = self.text_input_buffer[:-1]
            return True
        else:
            ch = event.unicode
            if ch:
                self.text_input_buffer += ch
            return True

    def _commit_text_input(self, val: str, scene):
        """Process the completed text input based on input_target."""
        if self.input_target == "teleporter_dest":
            rc = self._pending_tp
            if rc and val:
                parsed = self.parse_tp_value(val)
                if parsed is None:
                    print("[EDITOR] invalid format! use: zone:row,col")
                    return  # keep input active
                dest_zone = parsed.get("zone", "")
                if dest_zone not in ZONE_MAPS:
                    print(f"[EDITOR] zone '{dest_zone}' doesn't exist")
                    self._pending_tp = None
                    self.text_input_active = False
                    self.text_input_buffer = ""
                    self.input_target = None
                    return
                # ── Portal-aware update ──────────────────────────────
                portal = get_portal_for_tile(scene.zone, rc[0], rc[1])
                if portal:
                    _this, other = get_portal_sides(portal, scene.zone)
                    other.spawn = (float(parsed["r"]), float(parsed["c"]))
                    # Rebuild lookup for this side
                    for tr, tc in _this.tiles:
                        _PORTAL_LOOKUP.setdefault(_this.zone, {})[
                            (tr, tc)
                        ] = (other.zone, other.spawn[0],
                             other.spawn[1], portal.id)
                    self.teleporters[rc] = {
                        "zone": dest_zone,
                        "r": int(parsed["r"]),
                        "c": int(parsed["c"]),
                        "portal_id": portal.id,
                    }
                    print(f"[EDITOR] portal '{portal.id}' spawn "
                          f"\u2192 {dest_zone}:{parsed['r']},{parsed['c']}")
                else:
                    # ── Create new portal ────────────────────────────
                    pid = f"{scene.zone}_{dest_zone}"
                    existing_ids = {p.id for p in ZONE_PORTALS}
                    n = 2
                    while pid in existing_ids:
                        pid = f"{scene.zone}_{dest_zone}_{n}"
                        n += 1
                    dr, dc = int(parsed["r"]), int(parsed["c"])
                    new_portal = Portal(
                        id=pid,
                        side_a=PortalSide(
                            zone=scene.zone,
                            tiles=[rc],
                            spawn=(float(rc[0] + 1), float(rc[1])),
                        ),
                        side_b=PortalSide(
                            zone=dest_zone,
                            tiles=[(dr, dc)],
                            spawn=(float(dr), float(dc)),
                        ),
                    )
                    ZONE_PORTALS.append(new_portal)
                    _PORTAL_LOOKUP.setdefault(scene.zone, {})[rc] = (
                        dest_zone, float(dr), float(dc), pid,
                    )
                    _PORTAL_LOOKUP.setdefault(dest_zone, {})[
                        (dr, dc)
                    ] = (scene.zone, float(rc[0] + 1),
                         float(rc[1]), pid)
                    self.teleporters[rc] = {
                        "zone": dest_zone, "r": dr, "c": dc,
                        "portal_id": pid,
                    }
                    scene.tiles[rc[0]][rc[1]] = 9
                    print(f"[EDITOR] created portal '{pid}': "
                          f"{scene.zone}({rc[0]},{rc[1]}) "
                          f"\u2194 {dest_zone}({dr},{dc})")
            elif rc and not val:
                print("[EDITOR] cancelled \u2014 no destination entered")
            self._pending_tp = None
        elif self.input_target == "zone_name":
            old = scene.zone
            scene.zone = val or scene.zone
            if old in ZONE_MAPS:
                ZONE_MAPS[scene.zone] = ZONE_MAPS.pop(old)
            if old in ZONE_ANCHORS:
                ZONE_ANCHORS[scene.zone] = ZONE_ANCHORS.pop(old)
            if old in ZONE_TELEPORTERS:
                ZONE_TELEPORTERS[scene.zone] = ZONE_TELEPORTERS.pop(old)
            print(f"[EDITOR] zone renamed: {old} -> {scene.zone}")
        elif self.input_target == "zone_create":
            new_zone = val.strip()
            if new_zone and new_zone not in ZONE_MAPS:
                ZONE_MAPS[new_zone] = [[1] * 30 for _ in range(30)]
                ZONE_ANCHORS[new_zone] = (15.0, 15.0)
                if save_zone_nbt:
                    try:
                        save_zone_nbt(new_zone, ZONE_MAPS[new_zone], anchor=(15.0, 15.0))
                    except Exception:
                        pass
                print(f"[EDITOR] created zone '{new_zone}'")
            elif new_zone in ZONE_MAPS:
                print(f"[EDITOR] zone '{new_zone}' already exists")
            else:
                print("[EDITOR] zone creation cancelled")
        self.text_input_active = False
        self.text_input_buffer = ""
        self.input_target = None

    def handle_mouse_down(self, event, app, scene):
        """Handle MOUSEBUTTONDOWN in editor mode."""
        from components import Camera
        cam = app.world.res(Camera) or Camera()
        rc = self.screen_to_tile(*event.pos, cam, app._virtual_size,
                                 scene.map_w, scene.map_h)
        if rc is None:
            return
        row, col = rc

        if event.button == 1:
            if self.teleporter_mode:
                self._handle_tp_click(row, col, scene)
            elif pygame.key.get_mods() & pygame.KMOD_SHIFT:
                self.mouse_drag_start = (row, col)
            else:
                self.paint_at(scene.tiles, row, col, scene.map_h, scene.map_w)

        elif event.button == 3:
            if self.teleporter_mode:
                if self.tp_move_mode and self._moving_tp is not None:
                    self._moving_tp = None
                    print("[EDITOR] move cancelled")
                elif (row, col) in self.teleporters:
                    tgt = self.teleporters[(row, col)]
                    pid = tgt.get("portal_id", "") if isinstance(tgt, dict) else ""
                    if pid:
                        # Remove tile from portal side
                        portal = get_portal_for_tile(scene.zone, row, col)
                        if portal:
                            this_side, _ = get_portal_sides(portal, scene.zone)
                            if (row, col) in this_side.tiles:
                                this_side.tiles.remove((row, col))
                            lk = _PORTAL_LOOKUP.get(scene.zone, {})
                            lk.pop((row, col), None)
                            # If no tiles remain on this side, remove the portal
                            if not this_side.tiles:
                                ZONE_PORTALS.remove(portal)
                                print(f"[EDITOR] portal '{pid}' deleted "
                                      f"(no tiles remain)")
                            else:
                                print(f"[EDITOR] removed tile ({row},{col}) "
                                      f"from portal '{pid}'")
                    del self.teleporters[(row, col)]
                    scene.tiles[row][col] = 1
                    if not pid:
                        print(f"[EDITOR] teleporter removed at ({row},{col})")
            else:
                if (row, col) in self.teleporters:
                    del self.teleporters[(row, col)]
                scene.tiles[row][col] = 1

    def _handle_tp_click(self, row, col, scene):
        """Left-click logic when in teleporter + move modes."""
        existing = self.teleporters.get((row, col))
        if self.tp_move_mode:
            if self._moving_tp is not None:
                old_rc = self._moving_tp
                new_rc = (row, col)
                if old_rc != new_rc:
                    tgt = self.teleporters.pop(old_rc)
                    self.teleporters[new_rc] = tgt
                    scene.tiles[old_rc[0]][old_rc[1]] = 1
                    scene.tiles[new_rc[0]][new_rc[1]] = 9
                    # Update portal tile list if applicable
                    portal = get_portal_for_tile(scene.zone, *old_rc)
                    if portal:
                        this_side, _ = get_portal_sides(portal, scene.zone)
                        if old_rc in this_side.tiles:
                            this_side.tiles.remove(old_rc)
                        if new_rc not in this_side.tiles:
                            this_side.tiles.append(new_rc)
                        # Rebuild lookup
                        lk = _PORTAL_LOOKUP.get(scene.zone, {})
                        entry = lk.pop(old_rc, None)
                        if entry:
                            lk[new_rc] = entry
                    print(f"[EDITOR] teleporter moved "
                          f"({old_rc[0]},{old_rc[1]}) \u2192 ({new_rc[0]},{new_rc[1]})")
                self._moving_tp = None
            elif existing:
                self._moving_tp = (row, col)
                pid = ""
                if isinstance(existing, dict):
                    pid = existing.get("portal_id", "")
                info = f" [portal '{pid}']" if pid else ""
                print(f"[EDITOR] picked up teleporter at "
                      f"({row},{col}){info} \u2014 click to place")
            else:
                print("[EDITOR] no teleporter here to move")
        else:
            self._pending_tp = (row, col)
            self.text_input_active = True
            self.input_target = "teleporter_dest"
            if existing:
                if isinstance(existing, dict):
                    pid = existing.get("portal_id", "")
                    self.text_input_buffer = (
                        f"{existing.get('zone','')}:"
                        f"{existing.get('r','')},{existing.get('c','')}"
                    )
                    if pid:
                        print(f"[EDITOR] editing portal '{pid}' "
                              f"\u2014 change destination spawn")
                else:
                    self.text_input_buffer = str(existing)
            else:
                self.text_input_buffer = ""


    # ── intent-driven update ────────────────────────────────────────

    def update_intents(self, input_mgr, scene, app):
        """Process editor-mode intents from the InputManager."""
        if input_mgr.just("toggle_debug"):
            scene.show_debug = not scene.show_debug
        if input_mgr.just("toggle_grid"):
            scene.show_grid = not scene.show_grid
        if input_mgr.just("ed_save"):
            self.save_zone(scene.zone, scene.tiles)
        if input_mgr.just("ed_exit"):
            scene.editor_active = False
            self.save_zone(scene.zone, scene.tiles)
        if input_mgr.just("ed_teleporter"):
            self.teleporter_mode = not self.teleporter_mode
            print(f"[EDITOR] teleporter mode {'ON' if self.teleporter_mode else 'OFF'}")
        if input_mgr.just("ed_anchor"):
            from components import Camera
            cam = app.world.res(Camera) or Camera()
            rc = self.screen_to_tile(*app.mouse_pos(), cam,
                                     app._virtual_size, scene.map_w, scene.map_h)
            if rc:
                ZONE_ANCHORS[scene.zone] = (rc[1] + 0.5, rc[0] + 0.5)
                print(f"[EDITOR] anchor set at ({rc[1]},{rc[0]})")
        if input_mgr.just("ed_new_zone"):
            self.text_input_active = True
            self.text_input_buffer = ""
            self.input_target = "zone_create"
            print("[EDITOR] type zone name to create (30x30 grass field)")
        if input_mgr.just("ed_rename"):
            self.text_input_active = True
            self.text_input_buffer = scene.zone
            self.input_target = "zone_name"
        if input_mgr.just("ed_move"):
            self.tp_move_mode = not self.tp_move_mode
            self._moving_tp = None
            print(f"[EDITOR] teleporter mode: {'MOVE' if self.tp_move_mode else 'PLACE'}")
        if input_mgr.just("ed_brush_down"):
            self.brush_size = max(1, self.brush_size - 1)
        if input_mgr.just("ed_brush_up"):
            self.brush_size = min(8, self.brush_size + 1)
        for ti in range(10):
            if input_mgr.just(f"ed_tile_{ti}"):
                self.selected_tile = ti

    def continuous_paint(self, app, scene, cam):
        """Called each frame — if mouse held, keep painting."""
        if (pygame.mouse.get_pressed()[0]
                and not self.mouse_drag_start
                and not self.teleporter_mode
                and not self.text_input_active):
            mx, my = app.mouse_pos()
            rc = self.screen_to_tile(mx, my, cam, app._virtual_size,
                                     scene.map_w, scene.map_h)
            if rc:
                self.paint_at(scene.tiles, rc[0], rc[1], scene.map_h, scene.map_w)

    # ── drawing ─────────────────────────────────────────────────────

    def draw(self, surface, app, scene, cam, ox, oy,
             start_row, start_col, end_row, end_col):
        """Render editor overlay (toolbar, teleporters, palette, etc.)."""
        sw, sh = surface.get_size()

        mode_tag = " [TELEPORTER MODE]" if self.teleporter_mode else ""
        move_tag = " [MOVE]" if self.tp_move_mode else ""
        txt = (f"EDITOR: zone={scene.zone} tile={self.selected_tile} "
               f"brush={self.brush_size}{mode_tag}{move_tag}  F4:exit  E:save")
        app.draw_text(surface, txt, 8, 48, (255, 200, 100))
        y = 64
        app.draw_text(
            surface,
            "[T] teleporter  [M] move  [N] new zone  [K] anchor  "
            "[Z] rename  [0-9] tile  [[] []] brush  [Shift+drag] fill",
            8, y, (180, 180, 180),
        )
        y += 18
        if self.text_input_active:
            if self.input_target == "teleporter_dest":
                app.draw_text(surface,
                              f"dest: {self.text_input_buffer}  (format: zone:row,col)",
                              8, y, (255, 255, 200))
            else:
                app.draw_text(surface, f"input: {self.text_input_buffer}",
                              8, y, (255, 255, 200))
            y += 16

        # Mouse cursor tile highlight
        mx, my = app.mouse_pos()
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < scene.map_h and 0 <= col < scene.map_w:
            rect = pygame.Rect(ox + col * TILE_SIZE, oy + row * TILE_SIZE,
                               TILE_SIZE, TILE_SIZE)
            pygame.draw.rect(surface, (255, 255, 255), rect, 2)

        # Changed-tile overlay
        if hasattr(scene, "_orig_tiles"):
            overlay = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
            overlay.fill((255, 0, 0, 100))
            for r in range(start_row, end_row):
                for c in range(start_col, end_col):
                    try:
                        if scene.tiles[r][c] != scene._orig_tiles[r][c]:
                            surface.blit(overlay, (ox + c * TILE_SIZE,
                                                   oy + r * TILE_SIZE))
                    except Exception:
                        pass

        # Teleporter / portal markers
        for (r, c), tgt in self.teleporters.items():
            if start_row <= r < end_row and start_col <= c < end_col:
                cx_px = ox + c * TILE_SIZE + TILE_SIZE // 2
                cy_px = oy + r * TILE_SIZE + TILE_SIZE // 2
                is_portal = isinstance(tgt, dict) and tgt.get("portal_id")
                color = (0, 200, 255) if is_portal else (180, 20, 180)
                pygame.draw.circle(surface, color, (cx_px, cy_px), 6)
                try:
                    label = "?"
                    if isinstance(tgt, str) and tgt:
                        label = tgt[0]
                    elif isinstance(tgt, dict):
                        label = (str(tgt.get("zone") or "?"))[0].upper()
                    app.draw_text(surface, label, cx_px - 4, cy_px - 8,
                                  (255, 255, 255))
                    # Destination info below marker for portals
                    if is_portal:
                        dest = (f"\u2192{tgt.get('zone','?')}:"
                                f"{tgt.get('r','?')},{tgt.get('c','?')}")
                        app.draw_text(surface, dest,
                                      cx_px - 20, cy_px + 10,
                                      (180, 220, 255))
                except Exception:
                    pass

        # Pending TP highlight
        if self._pending_tp:
            pr, pc = self._pending_tp
            if start_row <= pr < end_row and start_col <= pc < end_col:
                prect = pygame.Rect(ox + pc * TILE_SIZE, oy + pr * TILE_SIZE,
                                    TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, (255, 200, 0), prect, 3)

        # Moving TP highlight
        if self._moving_tp:
            mr, mc = self._moving_tp
            if start_row <= mr < end_row and start_col <= mc < end_col:
                mrect = pygame.Rect(ox + mc * TILE_SIZE, oy + mr * TILE_SIZE,
                                    TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, (0, 255, 100), mrect, 3)

        # Anchor marker
        anchor = ZONE_ANCHORS.get(scene.zone)
        if anchor:
            try:
                acx = ox + int(anchor[0] * TILE_SIZE)
                acy = oy + int(anchor[1] * TILE_SIZE)
                pygame.draw.circle(surface, (0, 200, 255), (acx, acy), 8, 2)
            except Exception:
                pass

        # Tile palette at bottom-left
        try:
            palette_x = 8
            palette_y = sh - TILE_SIZE - 8
            for i in range(10):
                pr = pygame.Rect(palette_x + i * (TILE_SIZE + 4), palette_y,
                                 TILE_SIZE, TILE_SIZE)
                colr = TILE_COLORS.get(i, (120, 120, 120))
                pygame.draw.rect(surface, colr, pr)
                if i == self.selected_tile:
                    pygame.draw.rect(surface, (255, 255, 0), pr, 3)
                else:
                    pygame.draw.rect(surface, (80, 80, 80), pr, 1)
                app.draw_text(surface, str(i), pr.x + 4, pr.y + 2,
                              (255, 255, 255))
        except Exception:
            pass
