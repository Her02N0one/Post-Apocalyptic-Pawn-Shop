"""
scenes/debug_scene.py — ECS Inspector

Push on top of any scene with F1. Browse all entities,
see their components and values in real time.

Controls:
  Escape      = close inspector
  Up/Down     = scroll entity list
  Left/Right  = switch between entity list and component detail
  Enter       = expand/collapse entity
"""

from __future__ import annotations
import pygame
from dataclasses import fields
from core.scene import Scene
from core.app import App


class DebugScene(Scene):
    def __init__(self):
        self.scroll = 0
        self.selected = 0
        self.expanded: set[int] = set()
        self.panel = "list"   # "list" or "detail"

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE or event.key == pygame.K_F1:
                app.pop_scene()
            elif event.key == pygame.K_UP:
                self.selected = max(0, self.selected - 1)
            elif event.key == pygame.K_DOWN:
                self.selected += 1
            elif event.key == pygame.K_RETURN:
                eids = sorted(app.world.debug_dump().keys())
                if 0 <= self.selected < len(eids):
                    eid = eids[self.selected]
                    if eid in self.expanded:
                        self.expanded.discard(eid)
                    else:
                        self.expanded.add(eid)

    def update(self, dt: float, app: App):
        pass  # no sim updates while inspecting

    def draw(self, surface: pygame.Surface, app: App):
        # Semi-transparent overlay
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        surface.blit(overlay, (0, 0))

        sw, sh = surface.get_size()
        dump = app.world.debug_dump()
        eids = sorted(dump.keys())
        self.selected = min(self.selected, len(eids) - 1)

        y = 10
        app.draw_text(surface, f"ECS INSPECTOR — {len(eids)} entities  [Esc] close  [Enter] expand",
                       10, y, (0, 255, 200), app.font_lg)
        y += 28

        # Column layout
        col_x = 10
        detail_x = sw // 2

        for i, eid in enumerate(eids):
            if y > sh - 20:
                break

            comps = dump[eid]
            is_selected = (i == self.selected)
            is_expanded = (eid in self.expanded)

            # Entity header
            comp_names = ", ".join(type(c).__name__ for c in comps)
            prefix = "▼" if is_expanded else "▶"
            color = (0, 255, 150) if is_selected else (180, 180, 180)
            app.draw_text(surface, f"{prefix} e{eid}: {comp_names}", col_x, y, color)
            y += 16

            if is_expanded:
                for comp in comps:
                    comp_name = type(comp).__name__
                    app.draw_text(surface, f"    {comp_name}:", col_x, y, (120, 200, 255))
                    y += 15

                    if hasattr(comp, '__dataclass_fields__'):
                        for f in fields(comp):
                            val = getattr(comp, f.name)
                            val_str = _format_value(val)
                            app.draw_text(surface, f"      {f.name}: {val_str}",
                                          col_x, y, (200, 200, 200), app.font_sm)
                            y += 13
                    else:
                        app.draw_text(surface, f"      {comp}",
                                      col_x, y, (200, 200, 200), app.font_sm)
                        y += 13

                    if y > sh - 20:
                        break


def _format_value(val, max_len: int = 50) -> str:
    """Format a component field value for display."""
    if isinstance(val, float):
        return f"{val:.2f}"
    if isinstance(val, dict):
        if len(val) == 0:
            return "{}"
        items = [f"{k}: {_format_value(v, 15)}" for k, v in list(val.items())[:5]]
        s = "{" + ", ".join(items) + "}"
        if len(val) > 5:
            s += f" ... +{len(val)-5}"
        return s
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
