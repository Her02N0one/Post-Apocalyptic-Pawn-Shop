"""
scenes/debug_scene.py — ECS Inspector

Push on top of any scene with F1. Browse all entities,
see their components and values in real time.

Controls:
  Escape / F1   = close inspector
  Up / Down     = scroll entity list
  Enter         = expand / collapse entity
  Tab           = cycle filter (All → NPCs → Combat → Items → Resources)
  S             = toggle AI summary panel (right side)
  PgUp / PgDn   = scroll fast
"""

from __future__ import annotations
import pygame
from dataclasses import fields
from core.scene import Scene
from core.app import App

# Filter categories
_FILTERS = ["All", "NPCs", "Combat", "Items", "Resources"]


class DebugScene(Scene):
    def __init__(self):
        self.scroll = 0
        self.selected = 0
        self.expanded: set[int] = set()
        self.filter_idx = 0
        self.show_ai_panel = True

    # ── input ────────────────────────────────────────────────────────
    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_F1):
                app.pop_scene()
            elif event.key == pygame.K_UP:
                self.selected = max(0, self.selected - 1)
            elif event.key == pygame.K_DOWN:
                self.selected += 1
            elif event.key == pygame.K_PAGEUP:
                self.selected = max(0, self.selected - 10)
            elif event.key == pygame.K_PAGEDOWN:
                self.selected += 10
            elif event.key == pygame.K_TAB:
                self.filter_idx = (self.filter_idx + 1) % len(_FILTERS)
                self.selected = 0
            elif event.key == pygame.K_s:
                self.show_ai_panel = not self.show_ai_panel
            elif event.key == pygame.K_RETURN:
                eids = self._filtered_eids(app)
                if 0 <= self.selected < len(eids):
                    eid = eids[self.selected]
                    if eid in self.expanded:
                        self.expanded.discard(eid)
                    else:
                        self.expanded.add(eid)

    def update(self, dt: float, app: App):
        pass  # no sim updates while inspecting

    # ── filtering ────────────────────────────────────────────────────
    def _filtered_eids(self, app: App) -> list[int]:
        from components import (Brain, Threat, AttackConfig, Inventory,
                                Player, Identity, Health, Faction)
        from components.resources import Meta

        dump = app.world.debug_dump()
        cat = _FILTERS[self.filter_idx]
        eids: list[int] = []
        for eid in sorted(dump.keys()):
            if eid == -1:
                if cat in ("All", "Resources"):
                    eids.append(eid)
                continue
            comp_types = {type(c).__name__ for c in dump[eid]}
            if cat == "All":
                eids.append(eid)
            elif cat == "NPCs":
                if "Brain" in comp_types or "Faction" in comp_types:
                    eids.append(eid)
            elif cat == "Combat":
                if "Threat" in comp_types or "AttackConfig" in comp_types or "Projectile" in comp_types:
                    eids.append(eid)
            elif cat == "Items":
                if "Inventory" in comp_types or "Loot" in comp_types or "LootTableRef" in comp_types:
                    eids.append(eid)
            elif cat == "Resources":
                if eid == -1:
                    eids.append(eid)
        return eids

    # ── draw ─────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, app: App):
        from components import (Brain, Threat, AttackConfig, Faction, Health,
                                Hunger, Identity, Inventory, Equipment,
                                Position, Lod, GameClock)
        from components.ai import Patrol

        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 210))
        surface.blit(overlay, (0, 0))

        sw, sh = surface.get_size()
        eids = self._filtered_eids(app)
        if eids:
            self.selected = min(self.selected, len(eids) - 1)
        else:
            self.selected = 0
        dump = app.world.debug_dump()

        # ── title bar ────────────────────────────────────────────────
        y = 8
        filter_str = _FILTERS[self.filter_idx]
        app.draw_text(surface, f"ECS INSPECTOR — {len(eids)} entities  filter:[{filter_str}]",
                      10, y, (0, 255, 200), app.font_lg)
        y += 22
        app.draw_text(surface, "[Esc] close  [Enter] expand  [Tab] filter  [S] AI panel  [PgUp/Dn] scroll",
                      10, y, (100, 100, 100), app.font_sm)
        y += 16

        # Panel split: left = entity list, right = AI summary
        right_w = sw // 3 if self.show_ai_panel else 0
        left_w = sw - right_w - 10

        # ── entity list (left) ───────────────────────────────────────
        col_x = 10
        list_y = y
        for idx, eid in enumerate(eids):
            if list_y > sh - 14:
                app.draw_text(surface, f"  ... +{len(eids) - idx} more (PgDn)",
                              col_x, list_y, (120, 120, 120), app.font_sm)
                break

            comps = dump.get(eid, [])
            is_selected = (idx == self.selected)
            is_expanded = (eid in self.expanded)

            # Identity / name shortcut
            name = None
            for c in comps:
                if type(c).__name__ == "Identity":
                    name = c.name
                    break

            # Header
            prefix = "▼" if is_expanded else "▶"
            sel_bg = (40, 60, 40) if is_selected else None
            header_color = (0, 255, 150) if is_selected else (180, 180, 180)
            if sel_bg:
                pygame.draw.rect(surface, sel_bg, (col_x - 2, list_y - 1, left_w, 15))

            comp_names = ", ".join(type(c).__name__ for c in comps)
            label = f"{prefix} e{eid}"
            if name:
                label += f" [{name}]"
            label += f": {comp_names}"
            # Truncate to fit left panel
            max_chars = left_w // 7
            if len(label) > max_chars:
                label = label[:max_chars - 3] + "..."
            app.draw_text(surface, label, col_x, list_y, header_color, app.font_sm)
            list_y += 15

            if is_expanded:
                for comp in comps:
                    if list_y > sh - 14:
                        break
                    comp_name = type(comp).__name__
                    # Color-code by category
                    cat_color = _comp_category_color(comp_name)
                    app.draw_text(surface, f"    {comp_name}:", col_x, list_y, cat_color, app.font_sm)
                    list_y += 13

                    if hasattr(comp, '__dataclass_fields__'):
                        for f in fields(comp):
                            if list_y > sh - 14:
                                break
                            val = getattr(comp, f.name)
                            val_str = _format_value(val, max_len=max_chars - 12)
                            app.draw_text(surface, f"      {f.name}: {val_str}",
                                          col_x, list_y, (200, 200, 200), app.font_sm)
                            list_y += 12
                            # Expand dicts on extra lines
                            if isinstance(val, dict) and len(val) > 0:
                                for dk, dv in list(val.items())[:10]:
                                    if list_y > sh - 14:
                                        break
                                    dv_str = _format_value(dv, 40)
                                    app.draw_text(surface, f"        {dk}: {dv_str}",
                                                  col_x, list_y, (170, 170, 140), app.font_sm)
                                    list_y += 11
                    else:
                        s = str(comp)
                        if len(s) > max_chars - 8:
                            s = s[:max_chars - 11] + "..."
                        app.draw_text(surface, f"      {s}",
                                      col_x, list_y, (200, 200, 200), app.font_sm)
                        list_y += 12

        # ── AI summary panel (right) ─────────────────────────────────
        if self.show_ai_panel:
            panel_x = sw - right_w
            # Separator line
            pygame.draw.line(surface, (60, 80, 60), (panel_x - 4, 8), (panel_x - 4, sh - 8), 1)

            py = 8
            app.draw_text(surface, "NPC AI SUMMARY", panel_x, py, (0, 220, 180), app.font_lg)
            py += 22

            clock = app.world.res(GameClock)
            if clock:
                scale = getattr(clock, "time_scale", 1.0)
                app.draw_text(surface, f"Clock: {clock.time:.1f}s  scale: {scale:.1f}x",
                              panel_x, py, (180, 180, 100), app.font_sm)
                py += 14

            # Gather all NPCs with brains
            npc_entries: list[tuple[int, str, str, str, str, str]] = []
            for eid, brain in app.world.all_of(Brain):
                ident = app.world.get(eid, Identity)
                name = ident.name if ident else f"e{eid}"
                faction = app.world.get(eid, Faction)
                fac_str = f"{faction.group}/{faction.disposition}" if faction else "-"

                # Brain activity
                active_str = "ON" if brain.active else "off"

                # Combat mode
                combat = brain.state.get("combat", {})
                if combat:
                    mode = combat.get("mode", "?")
                    los = combat.get("_los_blocked", False)
                    mode_str = mode
                    if los:
                        mode_str += "*"  # asterisk = LOS blocked
                else:
                    villager = brain.state.get("villager", {})
                    if villager:
                        mode_str = f"v:{villager.get('mode', '?')}"
                    else:
                        mode_str = "-"

                # Health
                hp = app.world.get(eid, Health)
                hp_str = f"{hp.current:.0f}/{hp.maximum:.0f}" if hp else "-"

                # Hunger
                hunger = app.world.get(eid, Hunger)
                hng_str = f"{hunger.current:.0f}" if hunger else "-"

                npc_entries.append((eid, name, fac_str, active_str, mode_str, hp_str, hng_str))

            # Table header
            py += 4
            header = f"{'Name':>10} {'Faction':>12} {'Act':>3} {'Mode':>8} {'HP':>7} {'Hng':>4}"
            app.draw_text(surface, header, panel_x, py, (100, 180, 160), app.font_sm)
            py += 13
            pygame.draw.line(surface, (60, 100, 80), (panel_x, py), (sw - 8, py), 1)
            py += 3

            for entry in npc_entries:
                if py > sh - 14:
                    remaining = len(npc_entries) - npc_entries.index(entry)
                    app.draw_text(surface, f"  +{remaining} more...",
                                  panel_x, py, (120, 120, 120), app.font_sm)
                    break
                eid_e, nm, fac, act, md, hp_s, hng = entry
                # Color by mode
                mode_c = {
                    "idle": (150, 150, 150), "chase": (255, 200, 80),
                    "attack": (255, 80, 80), "flee": (80, 180, 255),
                    "return": (180, 180, 80),
                }.get(md.rstrip("*"), (180, 180, 180))
                row = f"{nm:>10} {fac:>12} {act:>3} {md:>8} {hp_s:>7} {hng:>4}"
                app.draw_text(surface, row, panel_x, py, mode_c, app.font_sm)
                py += 12

            # Selected entity detail
            if eids and 0 <= self.selected < len(eids):
                sel_eid = eids[self.selected]
                brain = app.world.get(sel_eid, Brain)
                if brain:
                    py += 10
                    pygame.draw.line(surface, (60, 100, 80),
                                     (panel_x, py), (sw - 8, py), 1)
                    py += 6
                    ident = app.world.get(sel_eid, Identity)
                    sel_name = ident.name if ident else f"e{sel_eid}"
                    app.draw_text(surface, f"DETAIL: {sel_name} (e{sel_eid})",
                                  panel_x, py, (0, 255, 180), app.font_sm)
                    py += 14

                    # Full brain state dump
                    app.draw_text(surface, f"brain.kind: {brain.kind}  active: {brain.active}",
                                  panel_x, py, (180, 220, 255), app.font_sm)
                    py += 13
                    for sk, sv in brain.state.items():
                        if py > sh - 14:
                            break
                        if isinstance(sv, dict):
                            app.draw_text(surface, f"  {sk}:",
                                          panel_x, py, (120, 200, 255), app.font_sm)
                            py += 12
                            for dk, dv in sv.items():
                                if py > sh - 14:
                                    break
                                dv_str = _format_value(dv, 30)
                                app.draw_text(surface, f"    {dk}: {dv_str}",
                                              panel_x, py, (180, 180, 160), app.font_sm)
                                py += 11
                        else:
                            sv_str = _format_value(sv, 40)
                            app.draw_text(surface, f"  {sk}: {sv_str}",
                                          panel_x, py, (180, 180, 160), app.font_sm)
                            py += 12

                    # Threat / AttackConfig
                    threat = app.world.get(sel_eid, Threat)
                    atk = app.world.get(sel_eid, AttackConfig)
                    if threat:
                        py += 4
                        app.draw_text(surface, f"Threat: aggro={threat.aggro_radius:.0f} "
                                      f"leash={threat.leash_radius:.0f} "
                                      f"sensor_int={threat.sensor_interval:.2f}",
                                      panel_x, py, (200, 160, 120), app.font_sm)
                        py += 12
                    if atk:
                        app.draw_text(surface, f"Attack: type={atk.attack_type} "
                                      f"range={atk.range:.1f} cd={atk.cooldown:.2f} "
                                      f"last={atk.last_attack_time:.1f}",
                                      panel_x, py, (200, 160, 120), app.font_sm)
                        py += 12

                    # Patrol
                    patrol = app.world.get(sel_eid, Patrol)
                    if patrol:
                        app.draw_text(surface, f"Patrol: origin=({patrol.origin_x:.1f},{patrol.origin_y:.1f}) "
                                      f"radius={patrol.radius:.1f} speed={patrol.speed:.1f}",
                                      panel_x, py, (160, 200, 160), app.font_sm)
                        py += 12


def _comp_category_color(name: str) -> tuple[int, int, int]:
    """Return a color based on component category for visual grouping."""
    ai_comps = {"Brain", "Threat", "AttackConfig", "Patrol", "Task", "Memory", "GoalSet"}
    social_comps = {"Faction", "Dialogue", "Ownership", "CrimeRecord", "Locked"}
    combat_comps = {"Combat", "Loot", "LootTableRef", "Projectile", "Health", "Hurtbox"}
    spatial_comps = {"Position", "Velocity", "Collider", "Facing"}
    if name in ai_comps:
        return (120, 200, 255)  # blue
    if name in social_comps:
        return (200, 160, 255)  # purple
    if name in combat_comps:
        return (255, 140, 100)  # orange
    if name in spatial_comps:
        return (100, 255, 160)  # green
    return (200, 200, 200)  # grey


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
