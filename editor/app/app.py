"""editor/app/app.py — ZoneEditorApp: main class composing all editor mixins."""

from __future__ import annotations

import logging
import math
import sys
import time
from pathlib import Path

_log = logging.getLogger(__name__)

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
from editor.app.panels_pkg import PanelsMixin
from editor.app.dialogs import DialogsMixin
from editor.app.asset_browser import AssetBrowserMixin
from editor.app.data_viewers import DataViewersMixin
from editor.app.entity_textures import EntityTexturesMixin
from editor.app.entity_creator import EntityCreatorMixin
from editor.app.session_cfg import load_session, save_session, push_recent
from editor.input_context import InputStack
from editor.dialog_manager import DialogManager, DialogPropertyBridge
from editor.contexts import GlobalShortcutsContext, CapturedViewportContext


class ZoneEditorApp(
    DialogPropertyBridge,
    EventsMixin,
    ViewportMixin,
    RaycasterMixin,
    PanelsMixin,
    DialogsMixin,
    AssetBrowserMixin,
    DataViewersMixin,
    EntityTexturesMixin,
    EntityCreatorMixin,
):
    """Standalone 3D zone editor with ImGui panels.

    Composed from seven focused mixins:

    * :class:`EventsMixin`        — input routing and escape chains
    * :class:`ViewportMixin`      — GL quad rendering dispatch
    * :class:`RaycasterMixin`     — 2D raycaster preview camera
    * :class:`PanelsMixin`        — ImGui sidebar panels & overlays
    * :class:`DialogsMixin`       — modal dialogs (new, save-as, unsaved guard, etc.)
    * :class:`AssetBrowserMixin`  — floating texture browser window
    * :class:`DataViewersMixin`   — read-only TOML data browsers
    """

    # ── mouse_captured property (backed by InputStack) ────────────

    @property
    def mouse_captured(self) -> bool:
        """True when the viewport owns all input (replaces the old boolean)."""
        return self.input_stack.is_captured

    @mouse_captured.setter
    def mouse_captured(self, value: bool) -> None:
        """Backwards-compat setter.  ``True`` pushes, ``False`` pops
        the CapturedViewportContext (if not already in the desired state)."""
        if value and not self.input_stack.is_captured:
            self._capture_mouse()
        elif not value and self.input_stack.is_captured:
            self._release_mouse()

    # ── Init ──────────────────────────────────────────────────────

    def __init__(self, zone_name: str = ""):
        # Pygame + OpenGL
        pygame.init()

        # Restore saved window size / maximized state from session
        _sess = load_session()
        _init_w = _sess.get("window_w", WINDOW_W)
        _init_h = _sess.get("window_h", WINDOW_H)
        _was_maximized = _sess.get("window_maximized", False)

        self.screen = pygame.display.set_mode(
            (_init_w, _init_h), DOUBLEBUF | OPENGL | RESIZABLE,
        )
        pygame.display.set_caption(WINDOW_TITLE)
        _icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / "textures" / "icon" / "moonPAPS.png"
        if _icon_path.exists():
            pygame.display.set_icon(pygame.image.load(str(_icon_path)))
        self.clock = pygame.time.Clock()
        self._window_maximized: bool = False

        # Re-maximize if it was maximized last session
        if _was_maximized:
            try:
                import ctypes
                sdl_win = ctypes.cast(pygame.display.get_wm_info()["window"],
                                      ctypes.c_void_p)
                for _lib_name in ("libSDL2-2.0.so.0", "libSDL2.so", "SDL2"):
                    try:
                        _sdl2 = ctypes.CDLL(_lib_name)
                        break
                    except OSError:
                        continue
                else:
                    _sdl2 = None
                if _sdl2 is not None:
                    _sdl2.SDL_MaximizeWindow(sdl_win)
                    self._window_maximized = True
            except Exception:
                pass

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

        # Session persistence (MRU, layout, bookmarks)
        self._session = _sess

        # Input stack + dialog manager (must exist before any show_* write)
        self.input_stack = InputStack()
        self.dialog_manager = DialogManager()
        self._wants_quit: bool = False

        # Mutable state for texture browser (avoids class-level mutable defaults)
        self._ab_init()

        # Zone data
        self.all_zones: list[str] = list_zones()
        self.zone: Zone | None = None
        self.zone_name: str = ""
        self.dirty: bool = False

        # Texture atlas
        self.atlas = TextureAtlas()
        self.atlas.ensure_all()

        # Viewport — restore layout from session
        self.view_mode: str = self._session.get("view_mode", "3d")
        self._vp_tex: int = 0
        self._vp_surface: pygame.Surface | None = None
        self._vp_size: tuple[int, int] = (800, 600)
        # mouse_captured is now a property backed by the InputStack
        # Use actual SDL window size (accounts for maximize on start)
        _actual = pygame.display.get_window_size()
        self.win_size: tuple[int, int] = (_actual[0], _actual[1])
        self.left_panel_w: int = self._session.get("left_panel_w", LEFT_PANEL_W)
        self.right_panel_w: int = self._session.get("right_panel_w", RIGHT_PANEL_W)
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

        # Restore texture browser visibility from session
        self.show_texture_browser: bool = self._session.get(
            "show_texture_browser", False)

        # Camera bookmarks (list of dicts)
        self._camera_bookmarks: list[dict] = self._session.get(
            "camera_bookmarks", [])

        # Always start with a blank zone
        self._create_default_zone()
        # If a zone name was given on the command line, load it;
        # otherwise try to restore the last-opened zone from session.
        _restore = zone_name or self._session.get("last_zone", "")
        if _restore and _restore != "untitled" and _restore in self.all_zones:
            self._load_zone(_restore)

        # New-zone dialog state
        self.new_zone_w: int = 20
        self.new_zone_h: int = 20

        # Save-as dialog state
        self.save_as_name: str = ""

        # Unsaved changes guard
        self._guard_action: str = ""
        self._guard_payload: str = ""
        self._pending_quit: bool = False

        # Transient indicator (near-crosshair feedback)
        self._transient_text: str = ""
        self._transient_time: float = 0.0
        self._transient_color: tuple = (0.95, 0.90, 0.75, 1.0)

        # Keybind editor window state
        self._kb_capturing: str = ""   # action being rebound (empty = not capturing)
        self._kb_filter: str = ""      # search filter text
        self._kb_show_conflicts: bool = False  # filter to conflicts only

        # Resize Zone dialog state
        self._resize_new_w: int = 20
        self._resize_new_h: int = 20
        self._resize_anchor: str = "top-left"  # where old data is placed

        # Find / Replace Texture dialog state
        self._frt_find: str = ""
        self._frt_replace: str = ""
        self._frt_result: str = ""

        # Validate Zone results window state (ZoneIssue objects)
        self._validate_results: list = []

        # Persistent validation issues from last save (ZoneIssue list)
        self._save_issues: list = []

        # Zone preview subprocess
        self._preview_proc: object | None = None  # subprocess.Popen or None

        # Zone Settings dialog state
        self._zs_skybox: str = ""
        self._zs_sky_r: int = 0
        self._zs_sky_g: int = 0
        self._zs_sky_b: int = 0
        self._zs_anchor_r: float = 0.0
        self._zs_anchor_c: float = 0.0

        # Duplicate Zone dialog state
        self._dup_name: str = ""

        # Export Top-Down Image dialog state
        self._export_scale: int = 8
        self._export_entities: bool = True

        # Data viewer windows
        self._entity_defs_cache: dict | None = None
        self._dv_ent_filter: str = ""

        self._items_cache: dict | None = None
        self._dv_item_filter: str = ""

        self._loot_cache: dict | None = None
        self._presets_cache: dict | None = None

        # Entity texture manager state
        self._et_init()

        # Entity creator state
        self._ec_init()

        # Performance
        self.frame_ms: float = 0.0
        self.fps: float = 60.0

        # Bootstrap the input stack — GlobalShortcutsContext is always present
        self.input_stack.push(GlobalShortcutsContext(), self)

    # ── Zone loading / creation ───────────────────────────────────

    def _create_default_zone(self) -> None:
        """Create a blank untitled zone in memory (not saved to disk)."""
        self._create_new_zone(20, 20)

    def _attach_zone(self, zone: Zone, name: str) -> None:
        """Wire a zone into the editor and raycaster (shared init logic).

        Sets ``self.zone``, ``self.zone_name``, resets dirty flag, and
        creates-or-updates both the 3D editor and raycaster renderer.
        """
        self.zone = zone
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
                pitch_max=self._PITCH_MAX,
            )

        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 {name}")
        self._vp_dirty = True

    def _load_zone(self, name: str) -> None:
        try:
            zone = load_zone(name)
        except Exception as exc:                             # noqa: BLE001
            self._flash_transient(
                f"Failed to load {name}: {exc}", 3.0, (1.0, 0.4, 0.4, 1.0),
            )
            return
        self._attach_zone(zone, name)
        push_recent(self._session, name)

        self.px, self.py = self._find_spawn()
        self.angle = math.pi * 1.5
        self.player_fh = self.renderer.floor_height_at(self.px, self.py)
        self.cam_h = self.player_fh + EYE_HEIGHT
        self.is_interior = self.zone.first_person

    def _find_spawn(self) -> tuple[float, float]:
        zone = self.zone
        if not zone or not self.renderer:
            return 5.0, 5.0
        return find_spawn(zone, self.renderer.is_solid)

    def _create_new_zone(self, w: int, h: int) -> None:
        """Create a blank untitled zone in memory (not saved to disk)."""
        zone = Zone(
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
        self._attach_zone(zone, "untitled")

        self.px = w / 2.0
        self.py = h / 2.0
        self.angle = math.pi * 1.5
        self.player_fh = 0.0
        self.cam_h = EYE_HEIGHT
        self.is_interior = True

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

        # ── Validation gate ──────────────────────────────────────
        from core.zones.validation import validate_zone
        from core.entity_defs import entity_registry
        from core.tiles import TILE_REGISTRY
        from core.paths import TILE_TEX_DIR
        issues = validate_zone(
            self.zone,
            entity_registry=entity_registry(),
            tile_registry=TILE_REGISTRY,
            texture_dir=TILE_TEX_DIR,
        )
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        # Store persistently so the HUD can display them until next save
        self._save_issues = list(issues)
        if errors:
            n = len(errors)
            self._flash_transient(
                f"\u26a0 {n} validation error{'s' * (n > 1)} — see HUD",
                3.0, (1.0, 0.5, 0.2, 1.0))
            for e in errors:
                _log.warning("zone-validate ERROR: %s [%s]",
                             e.message, e.location or e.category)
        if warnings:
            for w in warnings:
                _log.info("zone-validate warn: %s [%s]",
                          w.message, w.location or w.category)

        path = ZONES_DIR / f"{name}.zone"
        try:
            self.zone.save_to_file(path, self.registry)
        except Exception as exc:  # noqa: BLE001
            self._flash_transient(
                f"Save failed: {exc}", 3.0, (1.0, 0.3, 0.3, 1.0))
            return
        self.dirty = False
        self._flash_transient(f"Saved {name} \u2713", 1.5, (0.5, 1.0, 0.6, 1.0))
        self.all_zones = list_zones()
        pygame.display.set_caption(f"{WINDOW_TITLE} \u2014 {name}")

    def _delete_zone_file(self, name: str) -> None:
        """Delete a .zone file from disk (not the currently loaded zone)."""
        path = ZONES_DIR / f"{name}.zone"
        try:
            path.unlink()
        except Exception as exc:  # noqa: BLE001
            self._flash_transient(
                f"Delete failed: {exc}", 2.0, (1.0, 0.4, 0.4, 1.0))
            return
        self.all_zones = list_zones()
        self._flash_transient(f"Deleted {name}", 1.5, (0.9, 0.6, 0.4, 1.0))

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
        """Enter edit mode: push CapturedViewportContext onto the InputStack."""
        if not self.input_stack.is_captured:
            self.input_stack.push(CapturedViewportContext(), self)

    def _release_mouse(self) -> None:
        """Leave edit mode: pop CapturedViewportContext from the InputStack."""
        if self.input_stack.is_captured:
            self.input_stack.remove("captured_viewport", self)

    # Low-level helpers called by CapturedViewportContext.on_push / on_pop

    def _do_capture_mouse(self) -> None:
        """Hide cursor, grab mouse, clear imgui state."""
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        pygame.mouse.get_rel()  # flush stale delta
        if self.editor_3d:
            self.editor_3d._capture_pending = False
            self.editor_3d._capture_name = ""
        self._clear_imgui_input_state()

    def _do_release_mouse(self) -> None:
        """Show cursor, ungrab mouse, clear imgui state."""
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        if self.editor_3d:
            self.editor_3d._lmb_held = False
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

            if self._pending_quit or self._wants_quit:
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

        self._save_session()
        self._kill_preview()
        self.imgui_impl.shutdown()
        pygame.quit()

    # ── Zone preview subprocess ──────────────────────────────────

    def _launch_preview(self) -> None:
        """Spawn (or re-focus) the standalone zone preview window."""
        import subprocess
        # Kill any existing preview first
        self._kill_preview()
        if not self.zone_name or self.zone_name == "untitled":
            self._flash_transient("Save zone first", 1.5, (1.0, 0.5, 0.2, 1.0))
            return
        # Ensure latest data is on disk
        if self.dirty:
            self._do_save(self.zone_name)
        script = Path(__file__).resolve().parent.parent.parent / "zone_preview.py"
        try:
            self._preview_proc = subprocess.Popen(
                [sys.executable, str(script), self.zone_name])
        except Exception as exc:  # noqa: BLE001
            _log.warning("Failed to launch preview: %s", exc)
            self._flash_transient(
                f"Preview launch failed: {exc}", 3.0, (1.0, 0.3, 0.3, 1.0))

    def _kill_preview(self) -> None:
        """Terminate the preview subprocess if running."""
        p = self._preview_proc
        if p is None:
            return
        try:
            p.poll()
            if p.returncode is None:
                p.terminate()
        except OSError:
            pass
        self._preview_proc = None

    @property
    def _preview_alive(self) -> bool:
        p = self._preview_proc
        if p is None:
            return False
        return p.poll() is None

    # ── Camera bookmarks ─────────────────────────────────────────

    def _save_camera_bookmark(self, slot: int) -> None:
        """Save the current 3D camera pose to bookmark *slot* (0-based)."""
        ed = self.editor_3d
        if not ed:
            return
        bm = {
            "slot": slot,
            "zone": self.zone_name,
            "cam_x": round(ed.cam_x, 3),
            "cam_y": round(ed.cam_y, 3),
            "cam_z": round(ed.cam_z, 3),
            "yaw": round(ed.yaw, 4),
            "pitch": round(ed.pitch, 4),
        }
        # Replace existing bookmark in same slot, or append
        bms = self._camera_bookmarks
        for i, b in enumerate(bms):
            if b.get("slot") == slot:
                bms[i] = bm
                self._flash_transient(
                    f"Bookmark {slot + 1} saved", 1.2, (0.5, 0.9, 0.6, 1.0))
                return
        bms.append(bm)
        self._flash_transient(
            f"Bookmark {slot + 1} saved", 1.2, (0.5, 0.9, 0.6, 1.0))

    def _recall_camera_bookmark(self, slot: int) -> None:
        """Recall camera pose from bookmark *slot* (0-based)."""
        ed = self.editor_3d
        if not ed:
            return
        for bm in self._camera_bookmarks:
            if bm.get("slot") == slot:
                # If bookmark is for a different zone, switch first
                bm_zone = bm.get("zone", "")
                if bm_zone and bm_zone != self.zone_name and bm_zone in self.all_zones:
                    if self._request_guarded("switch", bm_zone):
                        self._load_zone(bm_zone)
                    else:
                        return
                ed.cam_x = bm.get("cam_x", ed.cam_x)
                ed.cam_y = bm.get("cam_y", ed.cam_y)
                ed.cam_z = bm.get("cam_z", ed.cam_z)
                ed.yaw = bm.get("yaw", ed.yaw)
                ed.pitch = bm.get("pitch", ed.pitch)
                self._flash_transient(
                    f"Bookmark {slot + 1}", 1.0, (0.6, 0.8, 1.0, 1.0))
                return
        self._flash_transient(
            f"Bookmark {slot + 1}: empty", 0.8, (0.7, 0.5, 0.3, 1.0))

    def _delete_camera_bookmark(self, slot: int) -> None:
        """Remove camera bookmark at *slot*."""
        bms = self._camera_bookmarks
        self._camera_bookmarks = [b for b in bms if b.get("slot") != slot]

    def _save_session(self) -> None:
        """Persist editor session state to disk."""
        if self.zone_name != "untitled":
            self._session["last_zone"] = self.zone_name
        self._session["left_panel_w"] = self.left_panel_w
        self._session["right_panel_w"] = self.right_panel_w
        self._session["window_w"] = self.win_size[0]
        self._session["window_h"] = self.win_size[1]
        self._session["window_maximized"] = getattr(self, '_window_maximized', False)
        self._session["view_mode"] = self.view_mode
        self._session["show_texture_browser"] = getattr(
            self, "show_texture_browser", False)
        self._session["camera_bookmarks"] = getattr(
            self, "_camera_bookmarks", [])
        save_session(self._session)
