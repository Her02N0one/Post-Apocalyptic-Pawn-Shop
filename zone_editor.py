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
        1-6             Select tool (sculpt/paint/fill/erase/segment/select)
        LMB             Tool primary action
        RMB             Tool secondary action (inverse)
        MMB             Paint / eyedropper
        Scroll          Tool-specific (extend, cycle texture, selection height)

        Floor target:
          LMB=raise  RMB=lower  Scroll=extend  Shift+Scroll=snap grid

        Ceiling target (dig/fill model):
          LMB=dig (lower ceiling)  RMB=fill (raise ceiling)
          Scroll=upper wall height  Shift+Scroll=snap grid

        Select tool:
          LMB=set corners / fill texture
          RMB=clear textures  Del=reset cells  Esc=cancel
          Scroll=raise/lower selected heights
          X=toggle floor/ceiling mode

        R               Reset height on aimed cell
        Delete          Full cell reset
        G               Cycle snap height
        Ctrl+S          Save zone
        Ctrl+Z / Y      Undo / redo
        V               Toggle wall drawing

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
from core.zones import GameRegistry
from engine.textures import TextureAtlas
from engine.ray_renderer import RayRenderer
from editor.view_3d import Zone3DEditor, TOOLS, TOOL_LABELS, TOOL_COLORS, TOOL_HINTS, SNAP_Y_OPTIONS, _ensure_palette
from editor.fly_camera import MOUSE_SENS, wasd_2d

# ═══════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════

WINDOW_W      = 1600
WINDOW_H      = 900
WINDOW_TITLE  = "Zone Editor"

# Panel widths
LEFT_PANEL_W  = 280
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
        _icon_path = Path(__file__).resolve().parent / "assets" / "textures" / "icon" / "moonPAPS.png"
        if _icon_path.exists():
            pygame.display.set_icon(pygame.image.load(str(_icon_path)))
        self.clock = pygame.time.Clock()

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        # Disable sRGB framebuffer — some drivers enable it by default,
        # which double-gamma-corrects our already-sRGB pygame surfaces
        # and makes the viewport appear very dim.
        try:
            gl.glDisable(0x8DB9)  # GL_FRAMEBUFFER_SRGB
        except Exception:
            pass

        # ImGui
        imgui.create_context()
        self.imgui_impl = ImGuiRenderer()
        self._setup_theme()

        # Asset registry (for binary .zone saves)
        self.registry = GameRegistry()

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
        self.win_size: tuple[int, int] = (WINDOW_W, WINDOW_H)
        self.left_panel_w: int = LEFT_PANEL_W
        self.right_panel_w: int = RIGHT_PANEL_W
        self._dragging_splitter: str = ""  # "left" | "right" | ""

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
        self._create_new_zone(20, 20)

    def _load_zone(self, name: str) -> None:
        self.zone = load_zone(name)
        self.zone_name = name
        self.dirty = False

        if self.editor_3d:
            self.editor_3d.set_zone(self.zone)
        else:
            self.editor_3d = Zone3DEditor(self.zone)
            self.editor_3d.show_hud = False  # ImGui panels replace the pygame HUD

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

    def _create_new_zone(self, w: int, h: int) -> None:
        """Create a blank untitled zone in memory (not saved to disk)."""
        self.zone = Zone(
            name="untitled", width=w, height=h,
            anchor=(h / 2.0, w / 2.0),
            first_person=True,
            tiles=[["grass"] * w for _ in range(h)],
            floor_heights=[[0.0] * w for _ in range(h)],
            ceil_heights=[[10.0] * w for _ in range(h)],
            floor_textures=[[""] * w for _ in range(h)],
            ceil_textures=[[""] * w for _ in range(h)],
            wall_textures=[[""] * w for _ in range(h)],
            face_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
            light_levels=[[1.0] * w for _ in range(h)],
            rotations=[[0] * w for _ in range(h)],
            wall_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
            floor_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
            ceil_step_textures=[[[""] * 4 for _ in range(w)] for _ in range(h)],
            floor_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
            ceil_step_segments=[[[[], [], [], []] for _ in range(w)] for _ in range(h)],
            upper_wall_height=[[0.0] * w for _ in range(h)],
        )
        self.zone_name = "untitled"
        self.dirty = False

        if self.editor_3d:
            self.editor_3d.set_zone(self.zone)
        else:
            from editor.view_3d import Zone3DEditor
            self.editor_3d = Zone3DEditor(self.zone)
            self.editor_3d.show_hud = False  # ImGui panels replace the pygame HUD

        if self.renderer:
            self.renderer.update_zone(self.zone, self.atlas, self.dn)
        else:
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

        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 untitled")

    def _save_zone(self) -> None:
        """Save current zone.  If untitled, release mouse and prompt for a name."""
        if self.zone_name == "untitled" or not self.zone_name:
            if self.mouse_captured:
                self._release_mouse()
            self.save_as_name = ""
            self.show_save_as = True
        else:
            self._do_save(self.zone_name)

    def _do_save(self, name: str) -> None:
        """Actually write zone to disk under the given name."""
        if not self.zone:
            return
        self.zone.name = name
        self.zone_name = name
        path = ZONES_DIR / f"{name}.zone"
        self.zone.save_to_file(path, self.registry)
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
                old_w = self.win_size[0]
                self.win_size = (event.w, event.h)
                # Scale panel widths proportionally with window
                if old_w > 0:
                    ratio = event.w / old_w
                    self.left_panel_w = max(200, min(event.w // 2 - 50, int(self.left_panel_w * ratio)))
                    self.right_panel_w = max(200, min(event.w // 2 - 50, int(self.right_panel_w * ratio)))
                # Invalidate cached viewport surface so it gets recreated
                self._vp_surface = None
                self._vp_tex = 0
                self.imgui_impl.process_event(event)
                continue

            if self.mouse_captured:
                # ── CAPTURED: all input goes to the viewport ──
                if event.type == KEYDOWN:
                    # Escape: cancel selection first, then release mouse
                    if event.key == pygame.K_ESCAPE:
                        if (self.view_mode == "3d" and self.editor_3d
                                and self.editor_3d.tool == "select"
                                and (self.editor_3d._sel_start is not None
                                     or self.editor_3d._sel_end is not None)):
                            self.editor_3d._sel_cancel()
                        else:
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
        win_w, win_h = self.win_size
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
        # Reset shader program left active by the imgui renderer from the
        # previous frame — without this the fixed-function pipeline is
        # bypassed and the quad appears very dim.
        try:
            gl.glUseProgram(0)
        except Exception:
            pass

        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glOrtho(-1, 1, -1, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()

        # Disable blending so the viewport quad is drawn opaque —
        # on some platforms the non-SRCALPHA pygame surface produces
        # alpha=0 in the RGBA conversion, which makes the blended
        # result nearly invisible against the dark clear colour.
        gl.glDisable(gl.GL_BLEND)

        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._vp_tex)
        gl.glTexEnvi(gl.GL_TEXTURE_ENV, gl.GL_TEXTURE_ENV_MODE, gl.GL_REPLACE)
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)

        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0, 1); gl.glVertex2f(-1, -1)
        gl.glTexCoord2f(1, 1); gl.glVertex2f( 1, -1)
        gl.glTexCoord2f(1, 0); gl.glVertex2f( 1,  1)
        gl.glTexCoord2f(0, 0); gl.glVertex2f(-1,  1)
        gl.glEnd()

        gl.glDisable(gl.GL_TEXTURE_2D)
        # Re-enable blending for the imgui overlay pass
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPopMatrix()

    # ═══════════════════════════════════════════════════════════════
    #  ImGui UI
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self._menu_bar()
        self._left_panel()
        self._properties_panel()
        self._status_bar()
        self._draw_splitters()
        if self.show_new_zone:
            self._new_zone_dialog()
        if self.show_save_as:
            self._save_as_dialog()
        if not self.mouse_captured:
            self._capture_hint()

    # ── Draggable panel splitters ──────────────────────────────

    def _draw_splitters(self) -> None:
        """Draw invisible drag handles on the inner edges of both panels."""
        if self.mouse_captured:
            return
        win_w, win_h = self.win_size
        panel_h = win_h - MENU_BAR_H - STATUS_BAR_H
        GRIP = 8

        splitter_flags = (
            imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE
            | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_SCROLLBAR
            | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS
            | imgui.WINDOW_NO_FOCUS_ON_APPEARING | imgui.WINDOW_NO_NAV
        )

        min_pw = 200
        max_pw = win_w // 2 - 50

        # ── Left splitter ──
        lx = self.left_panel_w - GRIP // 2
        imgui.set_next_window_position(lx, MENU_BAR_H)
        imgui.set_next_window_size(GRIP, panel_h)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0, 0, 0, 0)
        imgui.push_style_color(imgui.COLOR_BORDER, 0, 0, 0, 0)
        imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (0, 0))
        imgui.begin("##LeftSplitter", flags=splitter_flags)
        imgui.invisible_button("##lsplit", GRIP, panel_h - 4)
        if imgui.is_item_active():
            mx = pygame.mouse.get_pos()[0]
            self.left_panel_w = max(min_pw, min(max_pw, mx))
            self._dragging_splitter = "left"
        elif self._dragging_splitter == "left":
            self._dragging_splitter = ""
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MOUSE_CURSOR_RESIZE_EW)
        imgui.end()
        imgui.pop_style_var()
        imgui.pop_style_color(2)

        # ── Right splitter ──
        rx = win_w - self.right_panel_w - GRIP // 2
        imgui.set_next_window_position(rx, MENU_BAR_H)
        imgui.set_next_window_size(GRIP, panel_h)
        imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, 0, 0, 0, 0)
        imgui.push_style_color(imgui.COLOR_BORDER, 0, 0, 0, 0)
        imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (0, 0))
        imgui.begin("##RightSplitter", flags=splitter_flags)
        imgui.invisible_button("##rsplit", GRIP, panel_h - 4)
        if imgui.is_item_active():
            mx = pygame.mouse.get_pos()[0]
            self.right_panel_w = max(min_pw, min(max_pw, win_w - mx))
            self._dragging_splitter = "right"
        elif self._dragging_splitter == "right":
            self._dragging_splitter = ""
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MOUSE_CURSOR_RESIZE_EW)
        imgui.end()
        imgui.pop_style_var()
        imgui.pop_style_color(2)

    def _capture_hint(self) -> None:
        """Show 'Click to edit' overlay when mouse is not captured."""
        if not self.zone:
            return
        win_w, win_h = self.win_size
        cx = (self.left_panel_w + win_w - self.right_panel_w) * 0.5
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

    # ── Left panel: toolbox ───────────────────────────────────────

    _SNAP_LABELS = ("1/16", "1/8", "1/4", "1/2", "1")

    def _left_panel(self) -> None:
        """Unified left sidebar — tools, textures, hints, snap, display, zones."""
        win_w, win_h = self.win_size
        imgui.set_next_window_position(0, MENU_BAR_H)
        imgui.set_next_window_size(self.left_panel_w, win_h - MENU_BAR_H - STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS
                 | imgui.WINDOW_ALWAYS_VERTICAL_SCROLLBAR)
        imgui.begin("Toolbox", flags=flags)

        if not self.editor_3d:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)
            imgui.end()
            return

        ed = self.editor_3d
        spacing_x = imgui.get_style().item_spacing.x

        # ── Tool buttons (3 per row, compact) ──────────────────
        avail_w = imgui.get_content_region_available()[0]
        btn_w = (avail_w - 2 * spacing_x) / 3.0
        for i, tool_name in enumerate(TOOLS):
            if i % 3 != 0:
                imgui.same_line()
            is_active = ed.tool == tool_name
            r, g, b = [c / 255.0 for c in TOOL_COLORS[tool_name]]
            if is_active:
                imgui.push_style_color(imgui.COLOR_BUTTON, r, g, b, 0.6)
                imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, r, g, b, 0.8)
                imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, r, g, b, 0.95)
            if imgui.button(f"{i+1} {TOOL_LABELS[tool_name]}##{tool_name}", btn_w, 26):
                ed.tool = tool_name
            if is_active:
                imgui.pop_style_color(3)

        # ── Snap selector (single row) ─────────────────────────
        imgui.spacing()
        avail_w = imgui.get_content_region_available()[0]
        n_snap = len(SNAP_Y_OPTIONS)
        snap_btn_w = (avail_w - (n_snap - 1) * spacing_x) / n_snap
        for i, snap in enumerate(SNAP_Y_OPTIONS):
            if i > 0:
                imgui.same_line()
            is_sel = abs(ed.snap_y - snap) < 0.001
            if is_sel:
                imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.55, 0.35, 1.0)
            if imgui.button(f"{self._SNAP_LABELS[i]}##snap{i}", snap_btn_w, 20):
                ed.snap_y = snap
                ed.snap_idx = i
            if is_sel:
                imgui.pop_style_color()

        imgui.separator()

        # ── Texture palette (context-sensitive) ────────────────
        tool_name = ed.tool
        if tool_name in ("paint", "segment", "fill", "select"):
            if imgui.collapsing_header("Textures", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                palette = _ensure_palette()
                cur_tex = ed.current_texture
                cur_idx = ed.tex_idx

                # Current texture swatch + name
                tc = TILE_COLORS.get(cur_tex, (128, 128, 128))
                r0, g0, b0 = tc[0] / 255.0, tc[1] / 255.0, tc[2] / 255.0
                imgui.color_button("##curtex", r0, g0, b0, 1.0, 0, 14, 14)
                imgui.same_line()
                imgui.text(cur_tex)
                imgui.same_line()
                imgui.text_disabled(f"({cur_idx + 1}/{len(palette)})")

                # Scrollable palette list (adaptive height)
                remaining = imgui.get_content_region_available()[1]
                list_h = max(60, min(180, remaining - 160))
                child_w = imgui.get_content_region_available()[0]
                imgui.begin_child("##texlist", child_w, list_h,
                                  border=True)
                for pi, pname in enumerate(palette):
                    tc2 = TILE_COLORS.get(pname, (128, 128, 128))
                    pr, pg, pb = tc2[0] / 255.0, tc2[1] / 255.0, tc2[2] / 255.0
                    imgui.color_button(f"##p{pi}", pr, pg, pb, 1.0, 0, 10, 10)
                    imgui.same_line()
                    is_sel = pi == cur_idx
                    clicked, _ = imgui.selectable(f"{pname}##pal{pi}", is_sel)
                    if clicked:
                        ed.tex_idx = pi
                        ed.current_texture = pname
                imgui.end_child()

        # ── Context hints (compact key-aligned columns) ────────
        hint = TOOL_HINTS.get(ed.tool, {})
        if hint:
            imgui.separator()
            actions_dict = hint.get("actions", {})

            # Pick context key
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
            wrap_x = imgui.get_cursor_pos_x() + imgui.get_content_region_available()[0]
            for key, desc in actions.items():
                imgui.text_disabled(key)
                imgui.same_line(70)
                imgui.push_text_wrap_pos(wrap_x)
                imgui.text(desc)
                imgui.pop_text_wrap_pos()

            extra = hint.get("keys", "")
            if extra:
                imgui.push_text_wrap_pos(wrap_x)
                imgui.text_colored(extra, 0.55, 0.55, 0.4, 1.0)
                imgui.pop_text_wrap_pos()

        # ── Select tool state ──────────────────────────────────
        if ed.tool == "select":
            ceil_mode = getattr(ed, '_sel_ceiling_mode', False)
            mode_col = (0.55, 0.7, 0.9, 1.0) if ceil_mode else (0.7, 0.9, 0.55, 1.0)
            imgui.text_colored("Ceiling" if ceil_mode else "Floor", *mode_col)
            imgui.same_line()
            imgui.text_disabled("(X)")
            if ed._sel_start is not None and ed._sel_end is not None:
                bounds = ed._sel_bounds()
                if bounds:
                    r1, c1, r2, c2 = bounds
                    area = (r2 - r1 + 1) * (c2 - c1 + 1)
                    imgui.text_disabled(f"{area} cells selected")

        # ── Display options (collapsed by default) ─────────────
        imgui.separator()
        if imgui.collapsing_header("Display")[0]:
            _, ed.show_walls = imgui.checkbox("Walls (V)", ed.show_walls)
            _, ed.show_ceiling_grid = imgui.checkbox(
                "Ceiling Grid", ed.show_ceiling_grid)
            _, ed.show_grid = imgui.checkbox("Floor Grid", ed.show_grid)
            _, ed.show_axes = imgui.checkbox("Axes", ed.show_axes)

        # ── View mode toggle ───────────────────────────────────
        full_w = imgui.get_content_region_available()[0]
        mode_label = "Preview" if self.view_mode == "3d" else "Editor"
        if imgui.button(f"Switch to {mode_label} (Tab)", full_w, 24):
            self._toggle_view_mode()

        # ── Zones list ─────────────────────────────────────────
        imgui.separator()
        if imgui.collapsing_header("Zones", imgui.TREE_NODE_DEFAULT_OPEN)[0]:
            if imgui.button("+ New Zone", imgui.get_content_region_available()[0], 22):
                self.show_new_zone = True
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
        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w - self.right_panel_w, MENU_BAR_H)
        imgui.set_next_window_size(self.right_panel_w, win_h - MENU_BAR_H - STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS)
        imgui.begin("Inspector", flags=flags)

        if not self.zone:
            imgui.text_colored("No zone loaded", 0.5, 0.5, 0.5, 1.0)
            imgui.end()
            return

        zone = self.zone

        # ── Zone header (always visible) ──
        dirty_mark = " *" if self.dirty else ""
        imgui.text_colored(f"{self.zone_name}{dirty_mark}", 1.0, 0.9, 0.5, 1.0)
        imgui.same_line()
        imgui.text_disabled(f"{zone.width} x {zone.height}")
        imgui.separator()

        # ── Cell inspector ──
        if self.editor_3d and self.editor_3d.aimed:
            hit = self.editor_3d.aimed
            r, c = hit.row, hit.col

            if imgui.collapsing_header(f"Cell ({r}, {c})##cell",
                                       imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                td = tile_def(zone.tiles[r][c])
                tile_name = zone.tiles[r][c]
                is_wall = td and td.wall

                # Tile type badge
                imgui.text(tile_name)
                imgui.same_line()
                if is_wall:
                    imgui.text_colored("WALL", 0.9, 0.4, 0.3, 1.0)
                else:
                    imgui.text_colored("OPEN", 0.4, 0.8, 0.4, 1.0)

                # Heights (compact 2-column)
                fh = zone.floor_heights[r][c]
                ch = zone.ceil_heights[r][c]
                is_sky = ch >= 10.0 - 0.01
                gap = ch - fh

                imgui.columns(2, "##hcols", False)
                imgui.set_column_width(0, 55)

                imgui.text_disabled("Floor")
                imgui.next_column()
                if abs(fh) < 0.001:
                    imgui.text_colored("0.00", 0.6, 0.8, 0.6, 1.0)
                elif fh < 0:
                    imgui.text_colored(f"{fh:.2f}", 0.5, 0.6, 0.9, 1.0)
                else:
                    imgui.text(f"{fh:.2f}")
                imgui.next_column()

                imgui.text_disabled("Ceil")
                imgui.next_column()
                if is_sky:
                    imgui.text_colored("SKY", 0.4, 0.7, 1.0, 1.0)
                else:
                    imgui.text(f"{ch:.2f}")
                imgui.next_column()

                imgui.text_disabled("Gap")
                imgui.next_column()
                if gap < 0.5:
                    imgui.text_colored(f"{gap:.2f}", 0.9, 0.3, 0.3, 1.0)
                else:
                    imgui.text(f"{gap:.2f}")
                imgui.columns(1)

                # Upper wall height (only if nonzero)
                if zone.upper_wall_height and len(zone.upper_wall_height) > r:
                    uwh = zone.upper_wall_height[r][c]
                    if uwh > 0.01:
                        imgui.text_disabled("Upper wall")
                        imgui.same_line(80)
                        imgui.text(f"{uwh:.2f}")

                # Textures (compact label : value rows)
                imgui.spacing()
                wt = zone.wall_textures[r][c] if zone.wall_textures else ""
                ft = zone.floor_textures[r][c] if zone.floor_textures else ""
                ct = zone.ceil_textures[r][c] if zone.ceil_textures else ""

                for lbl, tex in (("Wall", wt), ("Floor", ft), ("Ceil", ct)):
                    imgui.text_disabled(lbl)
                    imgui.same_line(55)
                    if tex:
                        imgui.text(tex)
                    else:
                        imgui.text_colored("\u2014", 0.4, 0.4, 0.45, 1.0)

                # Face overrides (inline)
                if zone.face_textures:
                    faces = zone.face_textures[r][c]
                    for i, d in enumerate("NSEW"):
                        if faces[i]:
                            imgui.text_disabled(f"  {d}")
                            imgui.same_line(55)
                            imgui.text(faces[i])

                # Wall segments (tree node, collapsed)
                if zone.wall_segments:
                    segs = zone.wall_segments[r][c]
                    has_segs = any(face_segs for face_segs in segs)
                    if has_segs and imgui.tree_node("Segments"):
                        for fi, face_segs in enumerate(segs):
                            if face_segs:
                                fn = "NSEW"[fi]
                                for seg in face_segs:
                                    imgui.text_disabled(f"  {fn}")
                                    imgui.same_line(40)
                                    imgui.text(f"{seg[0]} @ {seg[1]:.2f}")
                        imgui.tree_pop()

                # Aimed target
                if hit.part:
                    imgui.spacing()
                    td_a = tile_def(zone.tiles[r][c])
                    is_wall_a = td_a and td_a.wall
                    face_label = _paint_target_label(hit.part, hit.face, is_wall_a)
                    if hit.part == "floor":
                        pc = (0.7, 0.9, 0.55, 1.0)
                    elif hit.part == "ceiling":
                        pc = (0.55, 0.7, 0.9, 1.0)
                    else:
                        pc = (0.95, 0.75, 0.35, 1.0)
                    imgui.text_colored(f"> {face_label}", *pc)

                    # Paint tool: brush + current
                    if self.editor_3d.tool == "paint":
                        tex = self.editor_3d.current_texture or zone.tiles[r][c]
                        cur = self._get_face_texture(zone, r, c, hit.part, hit.face)
                        imgui.text_disabled("Brush")
                        imgui.same_line(55)
                        imgui.text(tex)
                        imgui.text_disabled("Current")
                        imgui.same_line(55)
                        imgui.text(cur if cur else "\u2014")

        else:
            imgui.text_colored("Aim at a cell to inspect", 0.45, 0.45, 0.5, 1.0)

        # ── Zone settings (always visible) ──
        imgui.spacing()
        imgui.separator()
        if imgui.collapsing_header("Zone Settings")[0]:
            imgui.text_disabled("Size")
            imgui.same_line(55)
            imgui.text(f"{zone.width} x {zone.height}")
            imgui.spacing()

            # Spawn anchor
            ar, ac = zone.anchor if zone.anchor else (0.0, 0.0)
            imgui.text_disabled("Anchor")
            imgui.push_item_width(self.right_panel_w - 80)
            changed_r, new_ar = imgui.input_float("Row##anchor_r", ar, 0.5, 1.0)
            changed_c, new_ac = imgui.input_float("Col##anchor_c", ac, 0.5, 1.0)
            imgui.pop_item_width()
            if changed_r or changed_c:
                zone.anchor = (new_ar, new_ac)
                self.dirty = True
            if self.editor_3d and imgui.button("Set to Camera##anchor_cam"):
                zone.anchor = (self.editor_3d.cam_z, self.editor_3d.cam_x)
                self.dirty = True

            imgui.spacing()
            changed_fp, new_fp = imgui.checkbox("First Person", zone.first_person)
            if changed_fp:
                zone.first_person = new_fp
                self.dirty = True

        # ── Camera (always visible, collapsed by default) ──
        if self.editor_3d:
            if imgui.collapsing_header("Camera")[0]:
                ed = self.editor_3d
                imgui.columns(2, "##cam_cols", False)
                imgui.set_column_width(0, 45)
                for lbl, val in (("X", ed.cam_x), ("Y", ed.cam_y), ("Z", ed.cam_z)):
                    imgui.text_disabled(lbl)
                    imgui.next_column()
                    imgui.text(f"{val:.2f}")
                    imgui.next_column()
                imgui.text_disabled("Yaw")
                imgui.next_column()
                imgui.text(f"{math.degrees(ed.yaw):.0f}\u00b0")
                imgui.next_column()
                imgui.text_disabled("Pitch")
                imgui.next_column()
                imgui.text(f"{math.degrees(ed.pitch):.0f}\u00b0")
                imgui.columns(1)

        imgui.end()

    def _get_face_texture(self, zone, r: int, c: int, part: str, face: str) -> str:
        """Return the currently applied texture string for a given face."""
        from editor.view_3d.constants import FACE_IDX
        if face in FACE_IDX:
            fi = FACE_IDX[face]
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
        win_w, win_h = self.win_size
        imgui.set_next_window_position(0, win_h - STATUS_BAR_H)
        imgui.set_next_window_size(win_w, STATUS_BAR_H)
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE
                 | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR
                 | imgui.WINDOW_NO_SCROLL_WITH_MOUSE | imgui.WINDOW_NO_COLLAPSE)
        imgui.begin("##StatusBar", flags=flags)

        if self.zone:
            dirty = " *" if self.dirty else ""
            imgui.text(f"{self.zone_name}{dirty}")

            imgui.same_line(150)
            imgui.text_disabled(f"{self.zone.width} x {self.zone.height}")

            imgui.same_line(230)
            mode = "3D EDITOR" if self.view_mode == "3d" else "RAYCASTER"
            imgui.text_colored(mode, 0.5, 0.8, 1.0, 1.0)

            if self.editor_3d and self.view_mode == "3d":
                imgui.same_line(350)
                r, g, b = [c / 255.0 for c in TOOL_COLORS[self.editor_3d.tool]]
                imgui.text_colored(TOOL_LABELS[self.editor_3d.tool], r, g, b, 1.0)
                imgui.same_line(440)
                imgui.text_disabled(f"Snap: {self.editor_3d.snap_y}")
            elif self.view_mode == "2d":
                imgui.same_line(350)
                imgui.text_disabled(f"({self.px:.1f}, {self.py:.1f})")
                if self.noclip:
                    imgui.same_line()
                    imgui.text_colored("NOCLIP", 0.9, 0.4, 0.4, 1.0)

            if self.mouse_captured:
                imgui.same_line(max(win_w - 90, 500))
                imgui.text_colored("EDITING", 0.3, 1.0, 0.4, 1.0)
        else:
            imgui.text_disabled("Select or create a zone to begin")

        imgui.end()

    # ── New zone dialog ───────────────────────────────────────────

    def _new_zone_dialog(self) -> None:
        imgui.open_popup("New Zone")

        win_w, win_h = self.win_size
        imgui.set_next_window_position(win_w / 2 - 175, win_h / 2 - 100)
        imgui.set_next_window_size(350, 0)

        if imgui.begin_popup_modal("New Zone", flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text("Create a new blank zone:")
            imgui.text_colored("You can name it when you save.",
                               0.5, 0.5, 0.55, 1.0)
            imgui.spacing()

            _, self.new_zone_w = imgui.input_int("Width", self.new_zone_w)
            _, self.new_zone_h = imgui.input_int("Height", self.new_zone_h)

            self.new_zone_w = max(5, min(100, self.new_zone_w))
            self.new_zone_h = max(5, min(100, self.new_zone_h))

            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if imgui.button("Create", 150, 30):
                self._create_new_zone(self.new_zone_w, self.new_zone_h)
                self.show_new_zone = False
                imgui.close_current_popup()

            imgui.same_line()
            if imgui.button("Cancel", 150, 30):
                self.show_new_zone = False
                imgui.close_current_popup()

            imgui.end_popup()
        else:
            self.show_new_zone = False

    def _save_as_dialog(self) -> None:
        imgui.open_popup("Save As")

        win_w, win_h = self.win_size
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
