"""scenes/exhibits/pathfinding_exhibit.py — Pathfinding exhibit.

Click to place start/goal markers, paint walls, and watch A* in action.
"""

from __future__ import annotations
import time as _time
import pygame
from core.app import App
from core.constants import TILE_SIZE, TILE_WALL, TILE_GRASS
from core.zone import ZONE_MAPS
from logic.pathfinding import find_path
from scenes.exhibits.base import Exhibit
from scenes.exhibits.drawing import draw_diamond


class PathfindingExhibit(Exhibit):
    """Tab 3 — Pathfinding demo."""

    name = "Pathfinding"
    category = "Navigation"
    description = (
        "A* Pathfinding Sandbox\n"
        "\n"
        "Click to paint walls, set start/goal markers, and\n"
        "watch the A* pathfinder work in real time.  The path\n"
        "is recalculated whenever walls change.\n"
        "\n"
        "Pre-built walls create corridors and chokepoints to\n"
        "demonstrate how pathfinding navigates complex layouts.\n"
        "\n"
        "What to observe:\n"
        " - Path (cyan line) avoids walls and finds shortest route\n"
        " - Calculation time shown in ms (bottom bar)\n"
        " - Node count shows path complexity\n"
        "\n"
        "Controls:\n"
        " LMB          — paint / erase walls\n"
        " Shift+LMB    — set start point\n"
        " RMB          — set goal point\n"
        " [Space]      — clear and reset"
    )

    def __init__(self):
        self._pf_start: tuple[float, float] | None = None
        self._pf_goal: tuple[float, float] | None = None
        self._pf_path: list[tuple[float, float]] | None = None
        self._pf_calc_ms: float = 0.0
        self._painting: int | None = None
        self._zone: str = ""
        self._tiles: list[list[int]] = []

    def setup(self, app: App, zone: str, tiles: list[list[int]]) -> list[int]:
        self._zone = zone
        self._tiles = tiles
        self._pf_start = None
        self._pf_goal = None
        self._pf_path = None
        self._painting = None

        # Pre-populate walls for wall-margin demo
        W = TILE_WALL
        for r in range(3, 17):
            if r != 10:
                tiles[r][15] = W
        for c in range(3, 10):
            tiles[7][c] = W
        for r in range(3, 8):
            tiles[r][9] = W
        for c in range(18, 28):
            if c not in (22, 23):
                tiles[13][c] = W
        for r, c in [(5, 20), (5, 24), (15, 6), (15, 12)]:
            tiles[r][c] = W

        ZONE_MAPS[zone] = tiles
        self._pf_start = (3.5, 5.5)
        self._pf_goal = (26.5, 5.5)
        self._recalc_pf()
        return []

    def on_space(self, app: App) -> str | None:
        return "reset"

    def handle_event(self, event: pygame.event.Event, app: App,
                     mouse_to_tile) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            rc = mouse_to_tile()
            if rc is None:
                return False
            row, col = rc
            if event.button == 1:
                keys = pygame.key.get_mods()
                if keys & pygame.KMOD_SHIFT:
                    self._pf_start = (col + 0.5, row + 0.5)
                    self._recalc_pf()
                else:
                    cur = self._tiles[row][col]
                    self._painting = TILE_WALL if cur != TILE_WALL else TILE_GRASS
                    self._tiles[row][col] = self._painting
            elif event.button == 3:
                self._pf_goal = (col + 0.5, row + 0.5)
                self._recalc_pf()
            return True

        elif event.type == pygame.MOUSEMOTION:
            if self._painting is not None and pygame.mouse.get_pressed()[0]:
                rc = mouse_to_tile()
                if rc:
                    self._tiles[rc[0]][rc[1]] = self._painting
                    ZONE_MAPS[self._zone] = self._tiles
                return True

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self._painting is not None:
                self._painting = None
                ZONE_MAPS[self._zone] = self._tiles
                self._recalc_pf()
                return True

        return False

    def draw(self, surface: pygame.Surface, ox: int, oy: int,
             app: App, eids: list[int],
             tile_px: int = TILE_SIZE, flags=None):
        # Start marker
        if self._pf_start:
            sx = ox + int(self._pf_start[0] * tile_px)
            sy = oy + int(self._pf_start[1] * tile_px)
            pygame.draw.circle(surface, (0, 255, 100), (sx, sy), 5)
            app.draw_text(surface, "S", sx - 3, sy - 12, (0, 255, 100), app.font_sm)

        # Goal marker
        if self._pf_goal:
            gx = ox + int(self._pf_goal[0] * tile_px)
            gy = oy + int(self._pf_goal[1] * tile_px)
            draw_diamond(surface, (255, 50, 50), gx, gy, 5)
            app.draw_text(surface, "G", gx - 3, gy - 12, (255, 50, 50), app.font_sm)

        # Path
        if self._pf_path:
            prev = None
            if self._pf_start:
                prev = (ox + int(self._pf_start[0] * tile_px),
                        oy + int(self._pf_start[1] * tile_px))
            for wx, wy in self._pf_path:
                wpx = ox + int(wx * tile_px)
                wpy = oy + int(wy * tile_px)
                if prev:
                    pygame.draw.line(surface, (0, 200, 255), prev, (wpx, wpy), 2)
                pygame.draw.circle(surface, (0, 200, 255), (wpx, wpy), 3)
                prev = (wpx, wpy)

    def info_text(self, app: App, eids: list[int]) -> str:
        path_len = len(self._pf_path) if self._pf_path else 0
        return (f"Pathfinding: Shift+LMB=start  RMB=goal  LMB=walls  "
                f"Calc: {self._pf_calc_ms:.2f}ms  Path: {path_len} nodes  "
                f"[Space] clear")

    def _recalc_pf(self):
        if not self._pf_start or not self._pf_goal:
            self._pf_path = None
            return
        ZONE_MAPS[self._zone] = self._tiles
        t0 = _time.perf_counter()
        self._pf_path = find_path(
            self._zone,
            self._pf_start[0], self._pf_start[1],
            self._pf_goal[0], self._pf_goal[1],
        )
        self._pf_calc_ms = (_time.perf_counter() - t0) * 1000
