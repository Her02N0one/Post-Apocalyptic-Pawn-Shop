"""editor/app/app.py — ZoneEditorApp: main class composing all editor mixins."""

from __future__ import annotations

import math
import time
from pathlib import Path

import pygame
from pygame.locals import DOUBLEBUF, OPENGL, RESIZABLE

import OpenGL.GL as gl
import imgui
from imgui.integrations.pygame import PygameRenderer as ImGuiRenderer

from core.zones import load_zone, list_zones, Zone, find_spawn
from core.paths import ZONES_DIR
from core.zones import GameRegistry
from engine.textures import TextureAtlas
from engine.ray_renderer import RayRenderer
from editor.view_3d import Zone3DEditor

from editor.app.constants import (
    WINDOW_W, WINDOW_H, WINDOW_TITLE,
    LEFT_PANEL_W, RIGHT_PANEL_W,
    RAY_RES_W, RAY_RES_H, RAY_FOV,
    EYE_HEIGHT,
)
from editor.app.theme import setup_theme
from editor.app.events import EventsMixin
from editor.app.viewport import ViewportMixin
from editor.app.raycaster import RaycasterMixin
from editor.app.panels import PanelsMixin
from editor.app.dialogs import DialogsMixin


class ZoneEditorApp(
    EventsMixin,
    ViewportMixin,
    RaycasterMixin,
    PanelsMixin,
    DialogsMixin,
):
    """Standalone 3D zone editor with ImGui panels.

    Composed from five focused mixins:

    * :class:`EventsMixin`     — input routing and escape chains
    * :class:`ViewportMixin`   — GL quad rendering dispatch
    * :class:`RaycasterMixin`  — 2D raycaster preview camera
    * :class:`PanelsMixin`     — ImGui sidebar panels & overlays
    * :class:`DialogsMixin`    — modal dialogs (new, save-as, unsaved guard)
    """

    # ── Init ──────────────────────────────────────────────────────

    def __init__(self, zone_name: str = ""):
        # Pygame + OpenGL
        pygame.init()
        self.screen = pygame.display.set_mode(
            (WINDOW_W, WINDOW_H), DOUBLEBUF | OPENGL | RESIZABLE,
        )
        pygame.display.set_caption(WINDOW_TITLE)
        _icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / "textures" / "icon" / "moonPAPS.png"
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
        setup_theme()

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
        self.view_mode: str = "3d"       # "3d" = wireframe,  "2d" = raycaster
        self._vp_tex: int = 0
        self._vp_surface: pygame.Surface | None = None
        self._vp_size: tuple[int, int] = (800, 600)
        self.mouse_captured: bool = False
        self.win_size: tuple[int, int] = (WINDOW_W, WINDOW_H)
        self.left_panel_w: int = LEFT_PANEL_W
        self.right_panel_w: int = RIGHT_PANEL_W
        self._dragging_splitter: str = ""

        # 3D editor + raycaster (initialized by _load_zone)
        self.editor_3d: Zone3DEditor | None = None
        self.renderer: RayRenderer | None = None
        self.px: float = 0.0
        self.py: float = 0.0
        self.angle: float = math.pi * 1.5
        self.pitch: float = 0.0
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

        # Unsaved changes guard
        self._show_unsaved_guard: bool = False
        self._guard_action: str = ""
        self._guard_payload: str = ""
        self._pending_quit: bool = False

        # Transient indicator (near-crosshair feedback)
        self._transient_text: str = ""
        self._transient_time: float = 0.0
        self._transient_color: tuple = (0.95, 0.90, 0.75, 1.0)

        # Keybind editor window state
        self.show_keybind_editor: bool = False
        self._kb_capturing: str = ""   # action being rebound (empty = not capturing)
        self._kb_filter: str = ""      # search filter text
        self._kb_show_conflicts: bool = False  # filter to conflicts only

        # Performance
        self.frame_ms: float = 0.0
        self.fps: float = 60.0

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
            self.editor_3d.show_hud = False
        self.editor_3d.on_flash = self._flash_transient

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

        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 {name}")

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
            self.editor_3d = Zone3DEditor(self.zone)
            self.editor_3d.show_hud = False
        self.editor_3d.on_flash = self._flash_transient

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

    # ── Save ──────────────────────────────────────────────────────

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
        self._flash_transient(f"Saved {name} \u2713", 1.5, (0.5, 1.0, 0.6, 1.0))
        self.all_zones = list_zones()
        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 {name}")

    # ── Unsaved changes guard ─────────────────────────────────────

    def _request_guarded(self, action: str, payload: str = "") -> bool:
        """Start an action that may discard unsaved changes.

        If the zone is dirty, shows the Save/Discard/Cancel dialog and
        returns False (caller should abort).  If not dirty, returns True
        (caller can proceed immediately).
        """
        if self.dirty:
            if self.mouse_captured:
                self._release_mouse()
            self._guard_action = action
            self._guard_payload = payload
            self._show_unsaved_guard = True
            return False
        return True

    def _execute_guarded_action(self) -> None:
        """Execute the action that was deferred by the guard dialog."""
        action = self._guard_action
        payload = self._guard_payload
        self._guard_action = ""
        self._guard_payload = ""
        if action == "quit":
            self._pending_quit = True
        elif action == "switch":
            self._load_zone(payload)
        elif action == "new":
            self._create_new_zone(self.new_zone_w, self.new_zone_h)
            self.show_new_zone = False

    # ── Mouse capture ─────────────────────────────────────────────

    def _capture_mouse(self) -> None:
        """Enter edit mode: hide cursor, grab mouse, all input -> viewport."""
        self.mouse_captured = True
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        pygame.mouse.get_rel()  # flush stale delta
        if self.editor_3d:
            self.editor_3d._capture_pending = False
            self.editor_3d._capture_name = ""
        self._clear_imgui_input_state()

    def _release_mouse(self) -> None:
        """Leave edit mode: show cursor, ungrab, all input -> imgui panels."""
        self.mouse_captured = False
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        if self.editor_3d:
            self.editor_3d._lmb_held = False
            self.editor_3d._capture_pending = False
            self.editor_3d._capture_name = ""
            if getattr(self.editor_3d, '_capture_pending', False):
                self.editor_3d._capture_pending = False
                self.editor_3d._capture_name = ""
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

            if self._pending_quit:
                running = False

            if self._transient_time > 0:
                self._transient_time -= dt

            if self.mouse_captured:
                if self.view_mode == "3d" and self.editor_3d:
                    self.editor_3d.update(dt, True)
                    if self.editor_3d.dirty:
                        self.dirty = True
                elif self.view_mode == "2d" and self.renderer:
                    self._update_raycaster(dt)

            self._render_frame()

            self.frame_ms = (time.perf_counter() - t0) * 1000
            self.fps = self.clock.get_fps() or 60.0

            pygame.display.flip()

        self.imgui_impl.shutdown()
        pygame.quit()
