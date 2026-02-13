"""scenes/test_scene_base.py — Shared base class for test benches.

All test scenes (Gym, Zoo, Museum) inherit from this instead of raw
Scene.  It handles the boilerplate that was copy-pasted across all
three, as identified in STRESS_POINTS.md:

    * Camera / GameClock / Tuning setup
    * F1  → Debug overlay
    * F3  → Scene picker
    * F4  → Tuning hot-reload
    * Esc → pop scene
    * Mouse-to-tile conversion
    * Entity cleanup on exit
    * Shared drawing helpers (delegates to world_draw)
"""

from __future__ import annotations
import pygame
from core.scene import Scene
from core.app import App
from core.constants import TILE_SIZE
from core.zone import ZONE_MAPS
from components import Camera, GameClock
from components.dev_log import DevLog


class TestScene(Scene):
    """Base class for all test benches (Gym, Zoo, Museum).

    Subclasses must set ``self.zone``, ``self.tiles``, ``self.map_w``,
    and ``self.map_h`` before calling ``super().on_enter(app)``.
    Entity IDs appended to ``self._eids`` are auto-cleaned on exit.
    """

    def __init__(self):
        self.zone: str = ""
        self.tiles: list[list[int]] = []
        self.map_w: int = 0
        self.map_h: int = 0
        self._eids: list[int] = []
        self._camera: Camera | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_enter(self, app: App):
        w = app.world

        # Standard resources (don't overwrite if already present)
        if not w.res(Camera):
            w.set_res(Camera())
        self._camera = w.res(Camera)

        if not w.res(GameClock):
            w.set_res(GameClock())

        # DevLog — so debug overlay can show AI logs from test scenes
        if not w.res(DevLog):
            w.set_res(DevLog())

        # Tuning hot-reload
        from core import tuning as _tun_mod
        _tun_mod.load()

        # Register zone tiles for A*/pathfinding
        if self.zone and self.tiles:
            ZONE_MAPS[self.zone] = self.tiles

    def on_exit(self, app: App):
        """Kill all tracked entities and purge dead."""
        for eid in self._eids:
            if app.world.alive(eid):
                app.world.kill(eid)
        app.world.purge()
        self._eids.clear()

    # ── Shared input ─────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        """Handle shared debug/navigation keys.

        Subclasses should call ``super().handle_event(event, app)``
        **first**, then handle their own keys.
        """
        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_F1:
            from scenes.debug_scene import DebugScene
            app.push_scene(DebugScene())
        elif event.key == pygame.K_F3:
            from scenes.scene_picker import ScenePickerScene
            app.push_scene(ScenePickerScene())
        elif event.key == pygame.K_F4:
            from core import tuning as _tun_mod
            _tun_mod.load()
            print("[TestScene] Tuning reloaded.")
        elif event.key == pygame.K_ESCAPE:
            app.pop_scene()

    # ── Coordinate helpers ───────────────────────────────────────────

    def _cam_offset(self, surface: pygame.Surface) -> tuple[int, int]:
        """Return (ox, oy) pixel offset from the camera centre."""
        cam = self._camera or Camera()
        sw, sh = surface.get_size()
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)
        return ox, oy

    def _mouse_to_tile(self, app: App) -> tuple[int, int] | None:
        """Convert current mouse position to (row, col) or None."""
        cam = self._camera or Camera()
        mx, my = app.mouse_pos()
        sw, sh = app._virtual_size
        ox = sw // 2 - int(cam.x * TILE_SIZE)
        oy = sh // 2 - int(cam.y * TILE_SIZE)
        col = (mx - ox) // TILE_SIZE
        row = (my - oy) // TILE_SIZE
        if 0 <= row < self.map_h and 0 <= col < self.map_w:
            return row, col
        return None

    # ── Drawing helpers (delegates to world_draw) ────────────────────

    def _draw_tiles(self, surface: pygame.Surface, *, show_grid: bool = False):
        """Draw the tile map using the shared renderer."""
        from scenes.world_draw import draw_tiles
        ox, oy = self._cam_offset(surface)
        draw_tiles(surface, self.tiles, ox, oy, show_grid,
                   0, 0, self.map_h, self.map_w)

    def _draw_entities(self, surface: pygame.Surface, app: App):
        """Draw all entities in this zone using the shared renderer."""
        from scenes.world_draw import draw_entities
        ox, oy = self._cam_offset(surface)
        draw_entities(surface, app, ox, oy, self.zone, show_all_zones=False)

    def _draw_particles(self, surface: pygame.Surface, app: App):
        """Draw particles using the shared renderer."""
        from logic.particles import ParticleManager
        from scenes.world_draw import draw_particles
        pm = app.world.res(ParticleManager)
        if pm:
            ox, oy = self._cam_offset(surface)
            draw_particles(pm, surface, ox, oy, TILE_SIZE)
