#!/usr/bin/env python3
"""zone_editor.py — Standalone 3D Zone Editor with ImGui UI.

A dedicated application for sculpting zones in 3D with a professional
dockable-panel UI.  Includes a raycaster preview mode (Tab to toggle).

Usage
-----
    python zone_editor.py [zone_name]

Controls
--------
    Click viewport to enter edit mode (capture mouse).
    Escape releases the mouse back to the UI panels.

    3D Editor (when captured)
        W/S/A/D         Fly camera
        Mouse           Look around
        1-3             Select tool (sculpt/paint/segment)
        LMB             Tool primary action
        RMB             Tool secondary action (inverse)
        Shift+LMB       Stamp (sculpt)
        MMB             Paint
        T               Toggle sculpt target (floor ↔ ceiling)

        Floor target:
          LMB=raise  RMB=lower  Scroll=extend  Shift+Scroll=stamp height

        Ceiling target (dig/fill model):
          LMB=dig (floor drops, ceiling placed at old floor)
          RMB=fill (floor rises, ceiling removed when met)
          Scroll=upper wall height (0-10)  Shift+Scroll=stamp height

        R               Reset height on aimed cell
        Delete          Full cell reset
        G               Cycle snap height
        Ctrl+S          Save zone
        Ctrl+Z / Y      Undo / redo

    Raycaster Preview (when captured)
        W/S/A/D         Walk around
        Mouse           Look
        Shift           Sprint
        Ctrl            Slow walk
        I               Toggle interior rendering

    General
        Tab             Toggle 3D editor / raycaster
        Escape          Release mouse / quit
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import pygame
from pygame.locals import (
    DOUBLEBUF, OPENGL, RESIZABLE, QUIT,
    KEYDOWN, KEYUP, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL, VIDEORESIZE,
)
import OpenGL.GL as gl

import imgui
from imgui.integrations.pygame import PygameRenderer as ImGuiRenderer

# ── Project imports ───────────────────────────────────────────────
_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.zones import load_zone, list_zones, Zone, find_spawn
from core.tiles import TILE_REGISTRY, tile_def, TILE_COLORS
from core.paths import ZONES_DIR
from systems.textures import TextureAtlas
from systems.ray_renderer import RayRenderer
from editor.view_3d import Zone3DEditor, TOOLS, TOOL_LABELS, TOOL_COLORS, TOOL_HINTS, SNAP_Y_OPTIONS, _ensure_palette
from editor.fly_camera import MOUSE_SENS, wasd_2d

# ═══════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════

WINDOW_W      = 1600
WINDOW_H      = 900
WINDOW_TITLE  = "Zone Editor"

# Panel widths
LEFT_PANEL_W  = 220
RIGHT_PANEL_W = 250
MENU_BAR_H    = 22
STATUS_BAR_H  = 28

# Raycaster preview settings
RAY_RES_W     = 640
RAY_RES_H     = 360
RAY_FOV       = math.pi / 3

# Player movement (raycaster preview)
MOVE_SPEED    = 3.0
SPRINT_MULT   = 2.0
SLOW_MULT     = 0.3
EYE_HEIGHT    = 0.5
MAX_STEP_UP   = 0.5
HEAD_CLEARANCE = 0.4
CAM_LERP      = 8.0


# ═══════════════════════════════════════════════════════════════════
#  Paint target label helper
# ═══════════════════════════════════════════════════════════════════

def _paint_target_label(part: str, face: str, is_wall_tile: bool = False) -> str:
    """Return a human-readable label describing the paint target face."""
    if face == "ground":
        return ""
    _DIR = {"north": "N", "south": "S", "east": "E", "west": "W"}
    if face in _DIR:
        d = _DIR[face]
        if part == "floor":
            return f"Floor {d} Step"
        elif part == "ceiling":
            return f"Ceil {d} Step"
        elif is_wall_tile:
            return f"{d} Wall Face"
        else:
            return f"{d} Wall Face"
    elif face == "top":
        if part == "floor":
            return "Floor Surface"
        elif part in ("wall", "ceiling"):
            return "Ceiling Top"
    elif face == "bot":
        if part == "ceiling":
            return "Ceiling Underside"
        elif part in ("wall", "floor"):
            return "Floor Bottom"
    return f"{part} ({face})"


# ═══════════════════════════════════════════════════════════════════
#  GL Texture Helper
# ═══════════════════════════════════════════════════════════════════

def _upload_surface(surface: pygame.Surface, tex_id: int = 0) -> int:
    """Upload a pygame Surface to an OpenGL texture.  Returns texture ID."""
    w, h = surface.get_size()
    data = pygame.image.tostring(surface, "RGBA", False)

    if tex_id == 0:
        tex_id = int(gl.glGenTextures(1))
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
    gl.glTexImage2D(
        gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0,
        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data,
    )
    return tex_id


# ═══════════════════════════════════════════════════════════════════
#  Application
# ═══════════════════════════════════════════════════════════════════

class ZoneEditorApp:
    """Standalone 3D zone editor with ImGui panels."""

    # ── Init ──────────────────────────────────────────────────────

    def __init__(self, zone_name: str = ""):
        # Pygame + OpenGL
        pygame.init()
        self.screen = pygame.display.set_mode(
            (WINDOW_W, WINDOW_H), DOUBLEBUF | OPENGL | RESIZABLE,
        )
        pygame.display.set_caption(WINDOW_TITLE)
        self.clock = pygame.time.Clock()

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        # ImGui
        imgui.create_context()
        self.imgui_impl = ImGuiRenderer()
        self._setup_theme()

        # Zone data
        self.all_zones: list[str] = list_zones()
        self.zone: Zone | None = None
        self.zone_name: str = ""
        self.dirty: bool = False

        # Texture atlas
        self.atlas = TextureAtlas()
        self.atlas.ensure_all()

        # Viewport
        self.view_mode: str = "3d"      # "3d" = wireframe,  "2d" = raycaster
        self._vp_tex: int = 0
        self._vp_surface: pygame.Surface | None = None
        self._vp_size: tuple[int, int] = (800, 600)
        self.mouse_captured: bool = False  # click-to-capture, esc-to-release

        # 3D editor + raycaster (initialized by _load_zone)
        self.editor_3d: Zone3DEditor | None = None
        self.renderer: RayRenderer | None = None
        self.px: float = 0.0
        self.py: float = 0.0
        self.angle: float = math.pi * 1.5
        self.pitch: float = 0.0          # vertical look (radians, + = up)
        self.player_fh: float = 0.0
        self.cam_h: float = 0.5
        self.noclip: bool = False
        self.is_interior: bool = True
        self.dn: float = 1.0

        # Always start with a blank zone
        self._create_default_zone()
        # If a zone name was given on the command line, load it on top
        if zone_name and zone_name in self.all_zones:
            self._load_zone(zone_name)

        # New-zone dialog state
        self.show_new_zone: bool = False
        self.new_zone_name: str = ""
        self.new_zone_w: int = 20
        self.new_zone_h: int = 20

        # Save-as dialog state
        self.show_save_as: bool = False
        self.save_as_name: str = ""

        # Performance
        self.frame_ms: float = 0.0
        self.fps: float = 60.0

    # ── Theme ─────────────────────────────────────────────────────

    def _setup_theme(self) -> None:
        style = imgui.get_style()
        style.window_rounding = 4.0
        style.frame_rounding = 2.0
        style.scrollbar_rounding = 3.0
        style.grab_rounding = 2.0
        style.window_border_size = 1.0
        imgui.style_colors_dark(style)
        c = style.colors
        c[imgui.COLOR_WINDOW_BACKGROUND]           = (0.07, 0.07, 0.09, 0.90)
        c[imgui.COLOR_CHILD_BACKGROUND]            = (0.05, 0.05, 0.07, 1.00)
        c[imgui.COLOR_BORDER]                      = (0.22, 0.22, 0.28, 0.50)
        c[imgui.COLOR_FRAME_BACKGROUND]            = (0.13, 0.13, 0.17, 1.00)
        c[imgui.COLOR_FRAME_BACKGROUND_HOVERED]    = (0.19, 0.19, 0.24, 1.00)
        c[imgui.COLOR_FRAME_BACKGROUND_ACTIVE]     = (0.27, 0.27, 0.33, 1.00)
        c[imgui.COLOR_TITLE_BACKGROUND]            = (0.07, 0.07, 0.09, 1.00)
        c[imgui.COLOR_TITLE_BACKGROUND_ACTIVE]     = (0.11, 0.11, 0.15, 1.00)
        c[imgui.COLOR_BUTTON]                      = (0.16, 0.16, 0.22, 1.00)
        c[imgui.COLOR_BUTTON_HOVERED]              = (0.24, 0.24, 0.30, 1.00)
        c[imgui.COLOR_BUTTON_ACTIVE]               = (0.32, 0.32, 0.40, 1.00)
        c[imgui.COLOR_HEADER]                      = (0.16, 0.16, 0.22, 1.00)
        c[imgui.COLOR_HEADER_HOVERED]              = (0.24, 0.24, 0.30, 1.00)
        c[imgui.COLOR_HEADER_ACTIVE]               = (0.32, 0.32, 0.40, 1.00)
        c[imgui.COLOR_SEPARATOR]                   = (0.22, 0.22, 0.30, 1.00)
        c[imgui.COLOR_SCROLLBAR_BACKGROUND]        = (0.05, 0.05, 0.07, 1.00)
        c[imgui.COLOR_SCROLLBAR_GRAB]              = (0.22, 0.22, 0.30, 1.00)
        c[imgui.COLOR_SCROLLBAR_GRAB_HOVERED]      = (0.30, 0.30, 0.38, 1.00)
        c[imgui.COLOR_SCROLLBAR_GRAB_ACTIVE]       = (0.38, 0.38, 0.46, 1.00)
        c[imgui.COLOR_TAB]                         = (0.12, 0.12, 0.16, 1.00)
        c[imgui.COLOR_TAB_HOVERED]                 = (0.22, 0.22, 0.30, 1.00)
        c[imgui.COLOR_CHECK_MARK]                  = (0.45, 0.72, 1.00, 1.00)
        c[imgui.COLOR_SLIDER_GRAB]                 = (0.35, 0.55, 0.90, 1.00)
        c[imgui.COLOR_SLIDER_GRAB_ACTIVE]          = (0.45, 0.65, 1.00, 1.00)
        c[imgui.COLOR_MENUBAR_BACKGROUND]          = (0.10, 0.10, 0.13, 1.00)
        c[imgui.COLOR_POPUP_BACKGROUND]            = (0.08, 0.08, 0.11, 0.97)
        c[imgui.COLOR_TEXT]                         = (0.93, 0.93, 0.95, 1.00)
        c[imgui.COLOR_TEXT_DISABLED]                = (0.45, 0.45, 0.50, 1.00)

    # ── Zone loading / creation ───────────────────────────────────

    def _create_default_zone(self) -> None:
        """Create a blank untitled zone in memory (not saved to disk)."""
        w, h = 20, 20
        self.zone = Zone(
            name="untitled",
            width=w,
            height=h,
            anchor=(h / 2.0, w / 2.0),
            tiles=[["grass"] * w for _ in range(h)],
            first_person=True,
            floor_heights=[[0.0] * w for _ in range(h)],
            ceil_heights=[[10.0] * w for _ in range(h)],
            floor_textures=[[""] * w for _ in range(h)],
            ceil_textures=[[""] * w for _ in range(h)],
            wall_textures=[[""] * w for _ in range(h)],
            face_textures=[[["" for _ in range(4)] for _ in range(w)] for _ in range(h)],
            wall_segments=[[[[],[], [], []] for _ in range(w)] for _ in range(h)],
            light_levels=[[1.0] * w for _ in range(h)],
        )
        self.zone_name = "untitled"
        self.dirty = False

        self.editor_3d = Zone3DEditor(self.zone)
        self.renderer = RayRenderer(
            self.zone, self.atlas, sw=RAY_RES_W, sh=RAY_RES_H,
            fov=RAY_FOV, dn=self.dn,
        )

        self.px = w / 2.0
        self.py = h / 2.0
        self.angle = math.pi * 1.5
        self.player_fh = 0.0
        self.cam_h = EYE_HEIGHT
        self.is_interior = True

        pygame.display.set_caption(f"{WINDOW_TITLE} — untitled")

    def _load_zone(self, name: str) -> None:
        self.zone = load_zone(name)
        self.zone_name = name
        self.dirty = False

        if self.editor_3d:
            self.editor_3d.set_zone(self.zone)
        else:
            self.editor_3d = Zone3DEditor(self.zone)

        if self.renderer:
            self.renderer.update_zone(self.zone, self.atlas, self.dn)
        else:
            self.renderer = RayRenderer(
                self.zone, self.atlas, sw=RAY_RES_W, sh=RAY_RES_H,
                fov=RAY_FOV, dn=self.dn,
            )

        self.px, self.py = self._find_spawn()
        self.angle = math.pi * 1.5
        self.player_fh = self.renderer.floor_height_at(self.px, self.py)
        self.cam_h = self.player_fh + EYE_HEIGHT
        self.is_interior = self.zone.first_person

        pygame.display.set_caption(f"{WINDOW_TITLE} — {name}")

    def _find_spawn(self) -> tuple[float, float]:
        zone = self.zone
        if not zone or not self.renderer:
            return 5.0, 5.0
        return find_spawn(zone, self.renderer.is_solid)

    def _create_new_zone(self, name: str, w: int, h: int) -> None:
        tiles = [["grass"] * w for _ in range(h)]
        data = {
            "name": name, "width": w, "height": h,
            "anchor": [h / 2.0, w / 2.0],
            "first_person": True,
            "tiles": tiles,
            "floor_heights": [[0.0] * w for _ in range(h)],
            "ceil_heights": [[10.0] * w for _ in range(h)],  # open sky
        }
        path = ZONES_DIR / f"{name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.all_zones = list_zones()
        self._load_zone(name)

    def _save_zone(self) -> None:
        """Save current zone.  If untitled, prompt for a name."""
        if self.zone_name == "untitled" or not self.zone_name:
            self.save_as_name = ""
            self.show_save_as = True
        else:
            self._do_save(self.zone_name)

    def _do_save(self, name: str) -> None:
        """Actually write zone to disk under the given name."""
        if not self.zone or not self.editor_3d:
            return
        self.zone.name = name
        self.zone_name = name
        self.editor_3d._save()
        self.dirty = False
        self.all_zones = list_zones()
        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 {name}")

    # ── Mouse capture ─────────────────────────────────────────────

    def _capture_mouse(self) -> None:
        """Enter edit mode: hide cursor, grab mouse, all input → viewport."""
        self.mouse_captured = True
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        pygame.mouse.get_rel()  # flush stale delta
        # The LMB-down that triggered capture was sent to process_event(),
        # but the matching LMB-up will happen during captured mode and never
        # reach ImGui. Clear the stuck button now so ImGui doesn't think
        # LMB is held forever.
        self._clear_imgui_input_state()

    def _release_mouse(self) -> None:
        """Leave edit mode: show cursor, ungrab, all input → imgui panels."""
        self.mouse_captured = False
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        # Clear continuous-paint state so it doesn't persist across captures
        if self.editor_3d:
            self.editor_3d._lmb_held = False
        # During capture, key-up / button-up events never reached ImGui's
        # process_event, leaving io.mouse_down and io.keys_down stuck.
        # Flush everything so ImGui starts clean.
        self._clear_imgui_input_state()

    def _clear_imgui_input_state(self) -> None:
        """Reset all ImGui input state (mouse buttons, keys, modifiers)."""
        io = imgui.get_io()
        io.mouse_down[0] = False
        io.mouse_down[1] = False
        io.mouse_down[2] = False
        io.mouse_pos = pygame.mouse.get_pos()
        for i in range(len(self.imgui_impl.custom_key_map)):
            io.keys_down[i] = False
        io.key_ctrl = False
        io.key_shift = False
        io.key_alt = False
        io.key_super = False

    # ── Main loop ─────────────────────────────────────────────────

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            dt = min(dt, 0.05)
            t0 = time.perf_counter()

            running = self._process_events()

            # Update active viewport
            if self.mouse_captured:
                # Captured: full camera + movement
                if self.view_mode == "3d" and self.editor_3d:
                    self.editor_3d.update(dt, True)
                    if self.editor_3d.dirty:
                        self.dirty = True
                elif self.view_mode == "2d" and self.renderer:
                    self._update_raycaster(dt)
            # When not captured: camera is frozen, no WASD, no mouse look

            self._render_frame()

            self.frame_ms = (time.perf_counter() - t0) * 1000
            self.fps = self.clock.get_fps() or 60.0

            pygame.display.flip()

        self.imgui_impl.shutdown()
        pygame.quit()

    # ── Events ────────────────────────────────────────────────────

    def _process_events(self) -> bool:
        io = imgui.get_io()

        for event in pygame.event.get():
            if event.type == QUIT:
                return False
            if event.type == VIDEORESIZE:
                self.imgui_impl.process_event(event)
                continue

            if self.mouse_captured:
                # ── CAPTURED: all input goes to the viewport ──
                if event.type == KEYDOWN:
                    # Escape → release mouse back to UI
                    if event.key == pygame.K_ESCAPE:
                        self._release_mouse()
                        continue
                    # Global shortcuts
                    if event.key == pygame.K_TAB and self.zone:
                        if not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                            self._toggle_view_mode()
                            continue
                    if event.key == pygame.K_s and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        self._save_zone()
                        continue
                    # Forward to active view
                    if self.view_mode == "3d" and self.editor_3d:
                        self.editor_3d.handle_event(event)
                    elif self.view_mode == "2d":
                        self._raycaster_key(event)

                elif event.type == MOUSEBUTTONDOWN:
                    # All mouse buttons → editor tools (LMB/RMB/MMB)
                    if self.view_mode == "3d" and self.editor_3d:
                        self.editor_3d.handle_event(event)

                elif event.type == MOUSEBUTTONUP:
                    # Forward release for continuous paint tracking
                    if self.view_mode == "3d" and self.editor_3d:
                        self.editor_3d.handle_event(event)

                elif event.type == MOUSEWHEEL:
                    if self.view_mode == "3d" and self.editor_3d:
                        self.editor_3d.handle_event(event)
                # Don't feed anything to imgui while captured

            else:
                # ── NOT CAPTURED: all input goes to imgui ──
                self.imgui_impl.process_event(event)

                if event.type == KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return False
                    # Global shortcuts still work from panels
                    if event.key == pygame.K_TAB and self.zone:
                        if not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                            self._toggle_view_mode()
                            continue
                    if event.key == pygame.K_s and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        self._save_zone()
                        continue

                # Click on viewport (not on a panel) → capture mouse
                elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                    if not io.want_capture_mouse and self.zone:
                        self._capture_mouse()

        return True

    # ── View mode toggle ──────────────────────────────────────────

    def _toggle_view_mode(self) -> None:
        if not self.editor_3d or not self.renderer:
            return
        if self.view_mode == "3d":
            self.view_mode = "2d"
            self.px = self.editor_3d.cam_x
            self.py = self.editor_3d.cam_z
            self.angle = self.editor_3d.yaw + math.pi * 0.5
            # Clamp pitch from 3D editor (±81°) to raycaster range (±54°)
            self.pitch = max(-self._PITCH_MAX,
                             min(self._PITCH_MAX, self.editor_3d.pitch))
            self.renderer.update_zone(self.zone, self.atlas, self.dn)
            self.renderer._is_interior = int(self.is_interior)
            self.player_fh = self.renderer.floor_height_at(self.px, self.py)
            self.cam_h = self.player_fh + EYE_HEIGHT
        else:
            self.view_mode = "3d"
            self.editor_3d.cam_x = self.px
            self.editor_3d.cam_y = self.cam_h
            self.editor_3d.cam_z = self.py
            self.editor_3d.yaw = self.angle - math.pi * 0.5
            self.editor_3d.pitch = self.pitch  # sync pitch to 3D editor

    # ── Raycaster preview movement ────────────────────────────────

    def _raycaster_key(self, event: pygame.event.Event) -> None:
        """Handle raycaster-specific key presses."""
        if event.key == pygame.K_i:
            self.is_interior = not self.is_interior
            if self.renderer:
                self.renderer._is_interior = int(self.is_interior)
        elif event.key == pygame.K_g:
            self.noclip = not self.noclip

    # Pitch limits (radians) — ~55° up/down
    _PITCH_MAX = math.pi * 0.30

    def _update_raycaster(self, dt: float) -> None:
        """WASD movement + mouse look for raycaster preview."""
        if not self.renderer:
            return

        # Mouse look (horizontal + vertical)
        mx, my = pygame.mouse.get_rel()
        self.angle += mx * MOUSE_SENS
        self.pitch = max(-self._PITCH_MAX,
                         min(self._PITCH_MAX,
                             self.pitch - my * MOUSE_SENS))

        # Movement
        keys = pygame.key.get_pressed()
        speed = MOVE_SPEED
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= SPRINT_MULT
        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            speed *= SLOW_MULT

        dx, dy = wasd_2d(
            self.angle,
            keys[pygame.K_w], keys[pygame.K_s],
            keys[pygame.K_a], keys[pygame.K_d],
            speed, dt,
        )

        def try_move(mdx: float, mdy: float) -> None:
            nx, ny = self.px + mdx, self.py + mdy
            if self.noclip:
                self.px, self.py = nx, ny
                self.player_fh = self.renderer.floor_height_at(self.px, self.py)
                return
            if self.renderer.can_step_to(nx, self.py, self.player_fh,
                                         MAX_STEP_UP, HEAD_CLEARANCE):
                self.px = nx
            if self.renderer.can_step_to(self.px, ny, self.player_fh,
                                         MAX_STEP_UP, HEAD_CLEARANCE):
                self.py = ny
            self.player_fh = self.renderer.floor_height_at(self.px, self.py)

        # Apply movement through collision
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            try_move(dx, dy)

        # Smooth camera height
        target = self.player_fh + EYE_HEIGHT
        if abs(self.cam_h - target) < 0.001:
            self.cam_h = target
        else:
            self.cam_h += (target - self.cam_h) * min(1.0, CAM_LERP * dt)

    # ── Rendering ─────────────────────────────────────────────────

    def _render_frame(self) -> None:
        win_w, win_h = pygame.display.get_surface().get_size()
        gl.glViewport(0, 0, win_w, win_h)
        gl.glClearColor(0.06, 0.06, 0.08, 1.0)
        gl.glClear(int(gl.GL_COLOR_BUFFER_BIT))

        # 1. Render viewport to full-window surface → fullscreen GL quad
        self._vp_size = (win_w, win_h)
        if self.zone:
            self._render_viewport()
            if self._vp_tex:
                self._draw_fullscreen_quad()

        # 2. ImGui overlay panels on top
        io = imgui.get_io()
        io.display_size = (win_w, win_h)
        self.imgui_impl.process_inputs()
        imgui.new_frame()
        self._build_ui()
        imgui.render()
        self.imgui_impl.render(imgui.get_draw_data())

    def _get_vp_surface(self, w: int, h: int) -> pygame.Surface:
        if self._vp_surface is None or self._vp_surface.get_size() != (w, h):
            self._vp_surface = pygame.Surface((w, h))
        return self._vp_surface

    def _render_viewport(self) -> None:
        vw, vh = self._vp_size
        if vw < 16 or vh < 16:
            return

        surf = self._get_vp_surface(vw, vh)

        if self.view_mode == "3d" and self.editor_3d:
            self.editor_3d.draw(surf)
        elif self.view_mode == "2d" and self.renderer:
            frame = self.renderer.render(self.px, self.py, self.angle,
                                          self.cam_h, self.pitch)
            scaled = pygame.transform.scale(frame, (vw, vh))
            surf.blit(scaled, (0, 0))

        self._vp_tex = _upload_surface(surf, self._vp_tex)

    def _draw_fullscreen_quad(self) -> None:
        """Draw the viewport texture as a fullscreen GL quad (behind imgui)."""
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glOrtho(-1, 1, -1, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()

        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._vp_tex)
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)

        gl.glBegin(gl.GL_QUADS)
        # pygame.image.tostring(flipped=False): row 0 = pygame top → GL v=0
        # Map GL v=0 (pygame top) to screen top, GL v=1 (pygame bottom) to
        # screen bottom.
        gl.glTexCoord2f(0, 1); gl.glVertex2f(-1, -1)  # bottom-left
        gl.glTexCoord2f(1, 1); gl.glVertex2f( 1, -1)  # bottom-right
        gl.glTexCoord2f(1, 0); gl.glVertex2f( 1,  1)  # top-right
        gl.glTexCoord2f(0, 0); gl.glVertex2f(-1,  1)  # top-left
        gl.glEnd()

        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPopMatrix()

    # ═══════════════════════════════════════════════════════════════
    #  ImGui UI
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self._menu_bar()
        self._tool_panel()
        self._zone_panel()
        self._properties_panel()
        self._status_bar()
        if self.show_new_zone:
            self._new_zone_dialog()
        if self.show_save_as:
            self._save_as_dialog()
        if not self.mouse_captured:
            self._capture_hint()
        elif self.editor_3d and self.view_mode == "3d":
            self._crosshair_label()

    def _capture_hint(self) -> None:
        """Show 'Click to edit' overlay when mouse is not captured."""
        if not self.zone:
            return
        win_w, win_h = pygame.display.get_surface().get_size()
        cx = (LEFT_PANEL_W + win_w - RIGHT_PANEL_W) * 0.5
        cy = win_h * 0.5
        imgui.set_next_window_position(cx - 160, cy - 20)
        imgui.set_next_window_size(320, 0)
        flags = (imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_MOVE | imgui.WINDOW_ALWAYS_AUTO_RESIZE
                 | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
                 | imgui.WINDOW_NO_INPUTS)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.0, 0.0, 0.0, 0.55)
        imgui.begin("##CaptureHint", flags=flags)
        imgui.text_colored("   Click viewport to edit  |  Esc = quit",
                           0.85, 0.85, 0.85, 1.0)
        imgui.end()
        imgui.pop_style_color()

    def _crosshair_label(self) -> None:
        """Show a floating label near the crosshair with the aimed target info."""
        ed = self.editor_3d
        if not ed:
            return

        tool = ed.tool
        hit = ed.aimed
        zone = self.zone
        if not zone:
            return

        # Select tool shows selection state even without aim
        if tool == "select":
            if ed._sel_start is not None and ed._sel_end is None:
                label = "Click second corner"
            elif ed._sel_start is not None and ed._sel_end is not None:
                label = "LMB=Fill  RMB=Clear  Del=Reset  Esc=Cancel"
            else:
                label = "Click to start selection"
        elif not hit or hit.face == "ground":
            return
        else:
            td = tile_def(zone.tiles[hit.row][hit.col])
            is_wall = td and td.wall
            target = _paint_target_label(hit.part, hit.face, is_wall)
            if not target:
                return

            # Tool-specific prefix
            if tool == "paint":
                tex_name = ed.current_texture or zone.tiles[hit.row][hit.col]
                label = f"Paint: {target}  [{tex_name}]"
            elif tool == "fill":
                tex_name = ed.current_texture or "(default)"
                label = f"Fill: {target}  [{tex_name}]"
            elif tool == "erase":
                label = f"Erase: {target}"
            elif tool == "sculpt":
                label = f"Sculpt: {target}"
            elif tool == "segment":
                label = f"Segment: {target}"
            else:
                label = f"Target: {target}"

        # Position below crosshair
        win_w, win_h = pygame.display.get_surface().get_size()
        cx = win_w * 0.5
        cy = win_h * 0.5 + 24
        imgui.set_next_window_position(cx - 140, cy)
        imgui.set_next_window_size(0, 0)
        flags = (imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_MOVE | imgui.WINDOW_ALWAYS_AUTO_RESIZE
                 | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
                 | imgui.WINDOW_NO_INPUTS)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0.0, 0.0, 0.0, 0.60)
        imgui.begin("##CrosshairLabel", flags=flags)

        # Color based on tool / part
        r_c, g_c, b_c = [v / 255.0 for v in TOOL_COLORS.get(tool, (180, 180, 180))]
        if hit and hit.part == "floor":
            imgui.text_colored(label, 0.7, 0.9, 0.55, 1.0)
        elif hit and hit.part == "ceiling":
            imgui.text_colored(label, 0.55, 0.7, 0.9, 1.0)
        elif hit and hit.part == "wall":
            imgui.text_colored(label, 0.95, 0.75, 0.35, 1.0)
        else:
            imgui.text_colored(label, r_c, g_c, b_c, 1.0)

        imgui.end()
        imgui.pop_style_color()

    # ── Menu bar ──────────────────────────────────────────────────

    def _menu_bar(self) -> None:
        if imgui.begin_main_menu_bar():
            if imgui.begin_menu("File"):
                if imgui.menu_item("New Zone...")[0]:
                    self.show_new_zone = True
                imgui.separator()
                if imgui.menu_item("Save", "Ctrl+S")[0]:
                    self._save_zone()
                if imgui.menu_item("Save As...")[0]:
                    self.save_as_name = self.zone_name if self.zone_name != "untitled" else ""
                    self.show_save_as = True
                imgui.separator()
                if imgui.menu_item("Quit", "Escape")[0]:
                    pygame.event.post(pygame.event.Event(QUIT))
                imgui.end_menu()

            if imgui.begin_menu("Edit"):
                if imgui.menu_item("Undo", "Ctrl+Z")[0]:
                    if self.editor_3d:
                        self.editor_3d._undo()
                if imgui.menu_item("Redo", "Ctrl+Y")[0]:
                    if self.editor_3d:
                        self.editor_3d._redo()
                imgui.end_menu()

            if imgui.begin_menu("View"):
                clicked_3d, _ = imgui.menu_item(
                    "3D Editor", "Tab", self.view_mode == "3d")
                if clicked_3d and self.view_mode != "3d":
                    self._toggle_view_mode()
                clicked_ray, _ = imgui.menu_item(
                    "Raycaster Preview", "Tab", self.view_mode == "2d")
                if clicked_ray and self.view_mode != "2d":
                    self._toggle_view_mode()

                imgui.separator()
                if self.editor_3d:
                    _, self.editor_3d.show_axes = imgui.menu_item(
                        "Show Axes", "F4", self.editor_3d.show_axes)
                    _, self.editor_3d.show_walls = imgui.menu_item(
                        "Show Walls", "V", self.editor_3d.show_walls)
                    _, self.editor_3d.show_ceiling_grid = imgui.menu_item(
                        "Ceiling Grid", "F3", self.editor_3d.show_ceiling_grid)
                imgui.end_menu()

            # Right-aligned FPS
            spacing = max(0.0, imgui.get_window_width() - 220)
            imgui.same_line(spacing)
            if self.frame_ms < 10:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.4, 0.9, 0.4, 1.0)
            elif self.frame_ms < 20:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.9, 0.9, 0.3, 1.0)
            else:
                imgui.text_colored(f"{self.fps:.0f} FPS  {self.frame_ms:.1f}ms",
                                   0.9, 0.3, 0.3, 1.0)

            imgui.end_main_menu_bar()

    # ── Left panel: tools ─────────────────────────────────────────

    def _tool_panel(self) -> None:
        win_w, win_h = pygame.display.get_surface().get_size()
        imgui.set_next_window_position(0, MENU_BAR_H)
        imgui.set_next_window_size(LEFT_PANEL_W, (win_h - MENU_BAR_H - STATUS_BAR_H) * 0.55)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE)
        imgui.begin("Tools", flags=flags)

        if self.editor_3d:
            for i, tool_name in enumerate(TOOLS):
                label = TOOL_LABELS[tool_name]
                is_active = self.editor_3d.tool == tool_name
                r, g, b = [c / 255.0 for c in TOOL_COLORS[tool_name]]

                if is_active:
                    imgui.push_style_color(imgui.COLOR_BUTTON, r, g, b, 0.55)
                    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r, g, b, 0.75)
                    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r, g, b, 0.90)
                    imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 1.0, 1.0)

                btn_label = f"[{i+1}]  {label}"
                if imgui.button(btn_label, LEFT_PANEL_W - 16, 28):
                    self.editor_3d.tool = tool_name

                if is_active:
                    imgui.pop_style_color(4)

            # ── Texture picker (paint / fill / segment / select tools) ──
            tool_name = self.editor_3d.tool
            if tool_name in ("paint", "segment", "fill", "select"):
                imgui.spacing()
                imgui.separator()
                imgui.text("Texture  (Scroll to cycle)")
                imgui.spacing()

                palette = _ensure_palette()
                cur_tex = self.editor_3d.current_texture
                cur_idx = self.editor_3d.tex_idx

                # Current texture swatch + name
                tc = TILE_COLORS.get(cur_tex, (128, 128, 128))
                r0, g0, b0 = tc[0] / 255.0, tc[1] / 255.0, tc[2] / 255.0
                imgui.color_button("##curtex", r0, g0, b0, 1.0, 0, 18, 18)
                imgui.same_line()
                imgui.text(cur_tex)

                # Quick scroll buttons
                col_w = (LEFT_PANEL_W - 24) / 3
                if imgui.button("<< Prev##tex", col_w, 22):
                    new_i = (cur_idx - 1) % len(palette)
                    self.editor_3d.tex_idx = new_i
                    self.editor_3d.current_texture = palette[new_i]
                imgui.same_line()
                imgui.text(f" {cur_idx+1}/{len(palette)} ")
                imgui.same_line()
                if imgui.button("Next >>##tex", col_w, 22):
                    new_i = (cur_idx + 1) % len(palette)
                    self.editor_3d.tex_idx = new_i
                    self.editor_3d.current_texture = palette[new_i]

                # Scrollable palette list
                avail_h = min(150, len(palette) * 20)
                imgui.begin_child("##texlist", LEFT_PANEL_W - 16, avail_h,
                                  border=True)
                for pi, pname in enumerate(palette):
                    tc2 = TILE_COLORS.get(pname, (128, 128, 128))
                    pr, pg, pb = tc2[0] / 255.0, tc2[1] / 255.0, tc2[2] / 255.0
                    imgui.color_button(f"##p{pi}", pr, pg, pb, 1.0, 0, 12, 12)
                    imgui.same_line()
                    is_sel = pi == cur_idx
                    clicked, _ = imgui.selectable(f"{pname}##pal{pi}", is_sel)
                    if clicked:
                        self.editor_3d.tex_idx = pi
                        self.editor_3d.current_texture = pname
                imgui.end_child()

            # ── Tool hints (dynamically from TOOL_HINTS) ──
            hint = TOOL_HINTS.get(self.editor_3d.tool, {})
            if hint:
                imgui.spacing()
                imgui.separator()

                # Title
                title = hint.get("title", "")
                if title:
                    r_t, g_t, b_t = [c / 255.0 for c in TOOL_COLORS.get(self.editor_3d.tool, (180, 180, 180))]
                    imgui.text_colored(title, r_t, g_t, b_t, 1.0)
                    imgui.spacing()

                # Context-sensitive actions
                actions_dict = hint.get("actions", {})
                # Pick context
                ed = self.editor_3d
                if ed.tool == "select":
                    if ed._sel_start is not None and ed._sel_end is not None:
                        ctx_key = "active"
                    elif ed._sel_start is not None:
                        ctx_key = "started"
                    else:
                        ctx_key = "none"
                elif ed.tool == "sculpt":
                    part = ed.aimed.part if ed.aimed else None
                    if part == "ceiling":
                        ctx_key = "ceiling"
                    elif part in ("floor", "wall", "ground"):
                        ctx_key = "floor"
                    else:
                        ctx_key = "none"
                else:
                    ctx_key = "any"

                actions = actions_dict.get(ctx_key, actions_dict.get("any", {}))
                for key, desc in actions.items():
                    imgui.text_colored(f"  {key}: {desc}", 0.75, 0.75, 0.75, 1.0)

                # Extra keys line
                extra_keys = hint.get("keys", "")
                if extra_keys:
                    imgui.spacing()
                    imgui.text_colored(extra_keys, 0.6, 0.6, 0.4, 1.0)

            # Sculpt-specific: no longer has stamp height
            # Select tool: show selection state
            if self.editor_3d.tool == "select":
                imgui.spacing()
                ed = self.editor_3d
                if ed._sel_start is not None and ed._sel_end is not None:
                    bounds = ed._sel_bounds()
                    if bounds:
                        r1, c1, r2, c2 = bounds
                        area = (r2 - r1 + 1) * (c2 - c1 + 1)
                        imgui.text_colored(f"Selection: ({c1},{r1}) to ({c2},{r2})", 1.0, 0.9, 0.4, 1.0)
                        imgui.text_colored(f"Area: {area} cells", 0.8, 0.8, 0.8, 1.0)
                elif ed._sel_start is not None:
                    r, c = ed._sel_start
                    imgui.text_colored(f"Start: ({c},{r}) — click 2nd corner", 1.0, 0.9, 0.4, 1.0)
                else:
                    imgui.text_colored("Click a cell to start selection", 0.6, 0.6, 0.6, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.text("Snap Height")
            imgui.spacing()

            for i, snap in enumerate(SNAP_Y_OPTIONS):
                is_sel = abs(self.editor_3d.snap_y - snap) < 0.001
                if is_sel:
                    imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.55, 0.35, 1.0)
                col_w = (LEFT_PANEL_W - 24) / 2
                if imgui.button(f"{snap:.3f}##snap{i}", col_w, 24):
                    self.editor_3d.snap_y = snap
                    self.editor_3d.snap_idx = i
                if is_sel:
                    imgui.pop_style_color()
                if i % 2 == 0:
                    imgui.same_line()

            imgui.spacing()
            imgui.spacing()
            imgui.separator()

            # View mode switch button
            mode_label = "Raycaster Preview" if self.view_mode == "3d" else "3D Editor"
            if imgui.button(f"Tab: {mode_label}", LEFT_PANEL_W - 16, 28):
                self._toggle_view_mode()

            imgui.spacing()

            # Visibility toggles
            if imgui.collapsing_header("Display Options")[0]:
                if self.editor_3d:
                    _, self.editor_3d.show_walls = imgui.checkbox(
                        "Walls", self.editor_3d.show_walls)
                    _, self.editor_3d.show_ceiling_grid = imgui.checkbox(
                        "Ceiling Grid", self.editor_3d.show_ceiling_grid)
                    _, self.editor_3d.show_axes = imgui.checkbox(
                        "Axes", self.editor_3d.show_axes)
                    _, self.editor_3d.show_grid = imgui.checkbox(
                        "Floor Grid", self.editor_3d.show_grid)
        else:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)

        imgui.end()

    # ── Left panel: zone list ─────────────────────────────────────

    def _zone_panel(self) -> None:
        win_w, win_h = pygame.display.get_surface().get_size()
        top_h = (win_h - MENU_BAR_H - STATUS_BAR_H) * 0.55
        panel_y = MENU_BAR_H + top_h
        panel_h = win_h - panel_y - STATUS_BAR_H
        imgui.set_next_window_position(0, panel_y)
        imgui.set_next_window_size(LEFT_PANEL_W, panel_h)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE)
        imgui.begin("Zones", flags=flags)

        if imgui.button("+ New Zone", LEFT_PANEL_W - 16, 25):
            self.show_new_zone = True

        imgui.separator()

        for name in self.all_zones:
            is_loaded = (name == self.zone_name)
            if is_loaded:
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.82, 0.25, 1.0)

            clicked, _ = imgui.selectable(name, is_loaded)
            if clicked and name != self.zone_name:
                self._load_zone(name)

            if is_loaded:
                imgui.pop_style_color()

        imgui.end()

    # ── Right panel: properties ───────────────────────────────────

    def _properties_panel(self) -> None:
        win_w, win_h = pygame.display.get_surface().get_size()
        imgui.set_next_window_position(win_w - RIGHT_PANEL_W, MENU_BAR_H)
        imgui.set_next_window_size(RIGHT_PANEL_W, win_h - MENU_BAR_H - STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE)
        imgui.begin("Properties", flags=flags)

        if self.editor_3d and self.editor_3d.aimed and self.zone:
            hit = self.editor_3d.aimed
            zone = self.zone
            r, c = hit.row, hit.col

            # ── Cell info ──
            imgui.text_colored(f"Cell ({r}, {c})", 1.0, 0.85, 0.35, 1.0)
            imgui.separator()

            td = tile_def(zone.tiles[r][c])
            tile_name = zone.tiles[r][c]
            is_wall = td and td.wall

            imgui.text(f"Tile: {tile_name}")
            if is_wall:
                imgui.same_line()
                imgui.text_colored("[WALL]", 0.9, 0.4, 0.3, 1.0)
            else:
                imgui.same_line()
                imgui.text_colored("[OPEN]", 0.4, 0.8, 0.4, 1.0)

            # ── Heights ──
            imgui.spacing()
            if imgui.collapsing_header("Heights", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                fh = zone.floor_heights[r][c]
                ch = zone.ceil_heights[r][c]
                is_sky = ch >= 10.0 - 0.01

                imgui.columns(2, "##heights_cols", False)
                imgui.set_column_width(0, 80)

                imgui.text("Floor:")
                imgui.next_column()
                if abs(fh) < 0.001:
                    imgui.text_colored("0.00  (ground)", 0.6, 0.8, 0.6, 1.0)
                elif fh < 0:
                    imgui.text_colored(f"{fh:.2f}  (pit)", 0.5, 0.6, 0.9, 1.0)
                else:
                    imgui.text(f"{fh:.2f}")
                imgui.next_column()

                imgui.text("Ceiling:")
                imgui.next_column()
                if is_sky:
                    imgui.text_colored("SKY  (open)", 0.4, 0.7, 1.0, 1.0)
                else:
                    imgui.text(f"{ch:.2f}")
                imgui.next_column()

                imgui.text("Gap:")
                imgui.next_column()
                gap = ch - fh
                if gap < 0.5:
                    imgui.text_colored(f"{gap:.2f}", 0.9, 0.3, 0.3, 1.0)
                else:
                    imgui.text(f"{gap:.2f}")

                imgui.columns(1)

                # Upper wall height
                if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                    uwh = zone.upper_wall_height[r][c]
                    if uwh > 0.01:
                        imgui.text(f"Upper wall: {uwh:.2f}")

            # ── Textures ──
            imgui.spacing()
            if imgui.collapsing_header("Textures", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                def _tex_line(label: str, tex: str) -> None:
                    imgui.columns(2, f"##{label}_col", False)
                    imgui.set_column_width(0, 60)
                    imgui.text(f"{label}:")
                    imgui.next_column()
                    if tex:
                        imgui.text(tex)
                    else:
                        imgui.text_colored("(default)", 0.45, 0.45, 0.50, 1.0)
                    imgui.columns(1)

                wt = zone.wall_textures[r][c] if zone.wall_textures else ""
                ft = zone.floor_textures[r][c] if zone.floor_textures else ""
                ct = zone.ceil_textures[r][c] if zone.ceil_textures else ""
                _tex_line("Wall", wt)
                _tex_line("Floor", ft)
                _tex_line("Ceil", ct)

                # Face textures
                if zone.face_textures:
                    faces = zone.face_textures[r][c]
                    if any(f for f in faces):
                        imgui.spacing()
                        imgui.text("Face overrides:")
                        for i, direction in enumerate(["N", "S", "E", "W"]):
                            if faces[i]:
                                imgui.text(f"  {direction}: {faces[i]}")

            # ── Wall Segments ──
            if zone.wall_segments:
                segs = zone.wall_segments[r][c]
                has_segs = any(face_segs for face_segs in segs)
                if has_segs:
                    imgui.spacing()
                    if imgui.collapsing_header("Wall Segments")[0]:
                        face_names = ["N", "S", "E", "W"]
                        for fi, face_segs in enumerate(segs):
                            if face_segs:
                                imgui.text(f"  {face_names[fi]}:")
                                for seg in face_segs:
                                    imgui.text(f"    {seg[0]} @ {seg[1]:.2f}")

            # ── Aimed part ──
            imgui.spacing()
            imgui.separator()
            if hit.part:
                td_a = tile_def(zone.tiles[r][c])
                is_wall_a = td_a and td_a.wall
                face_label = _paint_target_label(hit.part, hit.face, is_wall_a)

                # Color by part type
                if hit.part == "floor":
                    pc = (0.7, 0.9, 0.55, 1.0)
                elif hit.part == "ceiling":
                    pc = (0.55, 0.7, 0.9, 1.0)
                else:
                    pc = (0.95, 0.75, 0.35, 1.0)

                imgui.text_colored(f"Target: {face_label}", *pc)

                # Paint mode: show what texture will be applied
                if self.editor_3d and self.editor_3d.tool == "paint":
                    tex = self.editor_3d.current_texture or zone.tiles[r][c]
                    imgui.text(f"  Brush: {tex}")
                    # Show current texture on this face
                    cur = self._get_face_texture(zone, r, c, hit.part, hit.face)
                    if cur:
                        imgui.text(f"  Current: {cur}")
                    else:
                        imgui.text_colored("  Current: (default)", 0.45, 0.45, 0.5, 1.0)

        elif self.zone:
            imgui.text_colored("Aim crosshair at a cell", 0.5, 0.5, 0.5, 1.0)
            imgui.spacing()
            imgui.separator()
            imgui.spacing()
            imgui.text("Camera")
            if self.editor_3d:
                imgui.text(f"  X: {self.editor_3d.cam_x:.2f}")
                imgui.text(f"  Y: {self.editor_3d.cam_y:.2f}")
                imgui.text(f"  Z: {self.editor_3d.cam_z:.2f}")
                imgui.text(f"  Yaw: {math.degrees(self.editor_3d.yaw):.0f}")
                imgui.text(f"  Pitch: {math.degrees(self.editor_3d.pitch):.0f}")
        else:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)

        imgui.end()

    def _get_face_texture(self, zone, r: int, c: int, part: str, face: str) -> str:
        """Return the currently applied texture string for a given face."""
        _FACE_IDX = {"north": 0, "south": 1, "east": 2, "west": 3}
        if face in _FACE_IDX:
            fi = _FACE_IDX[face]
            td = tile_def(zone.tiles[r][c])
            if td and td.wall:
                if zone.face_textures:
                    return zone.face_textures[r][c][fi]
            elif part == "floor" and hasattr(zone, "floor_step_textures") and zone.floor_step_textures:
                return zone.floor_step_textures[r][c][fi]
            elif part == "ceiling" and hasattr(zone, "ceil_step_textures") and zone.ceil_step_textures:
                return zone.ceil_step_textures[r][c][fi]
            elif zone.face_textures:
                return zone.face_textures[r][c][fi]
        elif face == "top":
            if part == "floor" and zone.floor_textures:
                return zone.floor_textures[r][c]
            elif part in ("wall", "ceiling") and zone.ceil_textures:
                return zone.ceil_textures[r][c]
        elif face == "bot":
            if part == "ceiling" and zone.ceil_textures:
                return zone.ceil_textures[r][c]
            elif part in ("wall", "floor") and zone.floor_textures:
                return zone.floor_textures[r][c]
        return ""

    # ── Status bar ────────────────────────────────────────────────

    def _status_bar(self) -> None:
        win_w, win_h = pygame.display.get_surface().get_size()
        imgui.set_next_window_position(0, win_h - STATUS_BAR_H)
        imgui.set_next_window_size(win_w, STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR
                 | imgui.WINDOW_NO_SCROLL_WITH_MOUSE | imgui.WINDOW_NO_COLLAPSE)
        imgui.begin("##StatusBar", flags=flags)

        if self.zone:
            dirty_mark = " *" if self.dirty else ""
            mode = "3D EDITOR" if self.view_mode == "3d" else "RAYCASTER"
            imgui.text(f"{self.zone_name}{dirty_mark}")
            imgui.same_line(150)
            imgui.text(f"{self.zone.width} x {self.zone.height}")
            imgui.same_line(240)
            imgui.text_colored(mode, 0.5, 0.8, 1.0, 1.0)

            if self.mouse_captured:
                imgui.same_line(350)
                imgui.text_colored("EDITING", 0.3, 1.0, 0.4, 1.0)

            if self.editor_3d and self.view_mode == "3d":
                imgui.same_line(440)
                tool_label = TOOL_LABELS.get(self.editor_3d.tool, self.editor_3d.tool.upper())
                r, g, b = [c / 255.0 for c in TOOL_COLORS[self.editor_3d.tool]]
                imgui.text_colored(f"Tool: {tool_label}", r, g, b, 1.0)
                imgui.same_line(600)
                imgui.text(f"Snap: {self.editor_3d.snap_y:.3f}")
            elif self.view_mode == "2d":
                imgui.same_line(440)
                imgui.text(f"Pos: ({self.px:.1f}, {self.py:.1f})")
                imgui.same_line(580)
                if self.noclip:
                    imgui.text_colored("NOCLIP", 0.9, 0.4, 0.4, 1.0)
        else:
            imgui.text("Ready — select or create a zone")

        imgui.end()

    # ── New zone dialog ───────────────────────────────────────────

    def _new_zone_dialog(self) -> None:
        imgui.open_popup("New Zone")

        win_w, win_h = pygame.display.get_surface().get_size()
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 100)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("New Zone", flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Create a new blank zone:")
            imgui.spacing()

            _, self.new_zone_name = imgui.input_text(
                "Name", self.new_zone_name, 64)
            _, self.new_zone_w = imgui.input_int("Width", self.new_zone_w)
            _, self.new_zone_h = imgui.input_int("Height", self.new_zone_h)

            self.new_zone_w = max(5, min(100, self.new_zone_w))
            self.new_zone_h = max(5, min(100, self.new_zone_h))

            name_clean = self.new_zone_name.strip()
            name_ok = bool(name_clean) and name_clean not in self.all_zones
            name_err = ""
            if name_clean and not name_ok:
                name_err = "Zone already exists!"
            elif not name_clean and self.new_zone_name:
                name_err = "Name cannot be blank"

            if name_err:
                imgui.text_colored(name_err, 0.9, 0.35, 0.35, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if not name_ok:
                imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
            if imgui.button("Create", 150, 30) and name_ok:
                self._create_new_zone(name_clean, self.new_zone_w, self.new_zone_h)
                self.show_new_zone = False
                self.new_zone_name = ""
                imgui.close_current_popup()
            if not name_ok:
                imgui.pop_style_var()

            imgui.same_line()
            if imgui.button("Cancel", 150, 30):
                self.show_new_zone = False
                self.new_zone_name = ""
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_new_zone = False

    def _save_as_dialog(self) -> None:
        imgui.open_popup("Save As")

        win_w, win_h = pygame.display.get_surface().get_size()
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 60)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("Save As", flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Save zone as:")
            imgui.spacing()

            _, self.save_as_name = imgui.input_text(
                "Name", self.save_as_name, 64)

            name_clean = self.save_as_name.strip()
            name_ok = bool(name_clean)
            exists = name_clean in self.all_zones
            name_err = ""
            if not name_clean and self.save_as_name:
                name_err = "Name cannot be blank"

            if name_err:
                imgui.text_colored(name_err, 0.9, 0.35, 0.35, 1.0)
            elif exists:
                imgui.text_colored("Will overwrite existing zone",
                                   0.9, 0.7, 0.2, 1.0)

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if not name_ok:
                imgui.push_style_var(imgui.STYLE_ALPHA, 0.4)
            if imgui.button("Save", 150, 30) and name_ok:
                self._do_save(name_clean)
                self.show_save_as = False
                self.save_as_name = ""
                imgui.close_current_popup()
            if not name_ok:
                imgui.pop_style_var()

            imgui.same_line()
            if imgui.button("Cancel", 150, 30):
                self.show_save_as = False
                self.save_as_name = ""
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_save_as = False


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    zone = sys.argv[1] if len(sys.argv) > 1 else ""
    ZoneEditorApp(zone).run()


if __name__ == "__main__":
    main()
