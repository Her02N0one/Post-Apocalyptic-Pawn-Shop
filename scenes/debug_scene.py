"""
scenes/debug_scene.py — Developer Tools (F1)

A tabbed fullscreen overlay for inspecting, observing, and live-editing
the game state.  Tabs:

  [1] AI Observer  — live NPC summary table + selected NPC detail
                     + scrolling action log from DevLog
  [2] ECS Browser  — entity list with filter, expand, color-coded fields
  [3] Entity Editor — modify selected entity's components in real time
  [4] Event Log    — raw DevLog feed with category filters

Controls (global):
  Escape / F1 = close
  1-4         = switch tab
  Up/Down     = scroll list      PgUp/PgDn = fast scroll
  Enter       = expand / select
  Tab         = cycle filter (ECS tab) / cycle log filter (Log tab)
  S           = toggle sidebar (AI tab)
"""

from __future__ import annotations
import pygame
from dataclasses import fields as dc_fields
from core.scene import Scene
from core.app import App
from components.dev_log import DevLog

# ── UI constants ─────────────────────────────────────────────────────
_BG = (16, 20, 24)
_PANEL_BG = (24, 28, 34)
_BORDER = (50, 60, 55)
_HEADER = (0, 255, 200)
_SUBHEADER = (100, 200, 180)
_DIM = (90, 90, 90)
_TEXT = (200, 200, 200)
_HIGHLIGHT_BG = (36, 56, 44)

_TAB_NAMES = ["AI Observer", "ECS Browser", "Entity Editor", "Event Log"]
_FILTER_CATS = ["All", "NPCs", "Combat", "Items", "Resources"]

_CAT_COLORS: dict[str, tuple[int, int, int]] = {
    "combat": (255, 100, 80),
    "attack": (255, 60, 60),
    "brain":  (120, 200, 255),
    "error":  (255, 50, 50),
    "move":   (100, 255, 160),
    "need":   (200, 180, 100),
    "system": (180, 180, 180),
    "edit":   (255, 220, 100),
}

_MODE_COLORS: dict[str, tuple[int, int, int]] = {
    "idle":   (150, 150, 150),
    "chase":  (255, 200, 80),
    "attack": (255, 80, 80),
    "flee":   (80, 180, 255),
    "return": (180, 180, 80),
}

_COMP_COLORS: dict[str, tuple[int, int, int]] = {
    "Brain": (120, 200, 255), "Threat": (120, 200, 255),
    "AttackConfig": (120, 200, 255), "HomeRange": (120, 200, 255),
    "Task": (120, 200, 255), "Memory": (120, 200, 255),
    "GoalSet": (120, 200, 255),
    "Faction": (200, 160, 255), "Dialogue": (200, 160, 255),
    "Ownership": (200, 160, 255), "CrimeRecord": (200, 160, 255),
    "Health": (255, 140, 100), "Combat": (255, 140, 100),
    "Loot": (255, 140, 100), "Projectile": (255, 140, 100),
    "Hurtbox": (255, 140, 100),
    "Position": (100, 255, 160), "Velocity": (100, 255, 160),
    "Collider": (100, 255, 160), "Facing": (100, 255, 160),
}


# ─────────────────────────────────────────────────────────────────────

class DebugScene(Scene):
    def __init__(self):
        self.tab = 0          # 0=AI, 1=ECS, 2=Editor, 3=Log
        self.selected = 0
        self.scroll = 0
        self.expanded: set[int] = set()
        self.filter_idx = 0
        self.show_sidebar = True
        self.log_scroll = 0
        self.log_cat_filter: str = ""  # "" = all
        # Editor state
        self.edit_eid: int | None = None
        self.edit_field_idx: int = 0
        self.edit_value: str = ""
        self.editing = False

    # ── input ────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, app: App):
        if event.type != pygame.KEYDOWN:
            return

        # If actively editing a text field, capture all keys
        if self.editing:
            if event.key == pygame.K_ESCAPE:
                self.editing = False
                return
            if event.key == pygame.K_RETURN:
                self._apply_edit(app)
                self.editing = False
                return
            if event.key == pygame.K_BACKSPACE:
                self.edit_value = self.edit_value[:-1]
                return
            if event.unicode and event.unicode.isprintable():
                self.edit_value += event.unicode
            return

        # Global keys
        if event.key in (pygame.K_ESCAPE, pygame.K_F1):
            app.pop_scene()
            return

        # Tab switching
        if event.key == pygame.K_1:
            self.tab = 0; self.selected = 0; return
        if event.key == pygame.K_2:
            self.tab = 1; self.selected = 0; return
        if event.key == pygame.K_3:
            self.tab = 2; self.selected = 0; return
        if event.key == pygame.K_4:
            self.tab = 3; self.log_scroll = 0; return

        # Navigation
        if event.key == pygame.K_UP:
            self.selected = max(0, self.selected - 1)
        elif event.key == pygame.K_DOWN:
            self.selected += 1
        elif event.key == pygame.K_PAGEUP:
            if self.tab == 3:
                self.log_scroll = max(0, self.log_scroll - 20)
            else:
                self.selected = max(0, self.selected - 15)
        elif event.key == pygame.K_PAGEDOWN:
            if self.tab == 3:
                self.log_scroll += 20
            else:
                self.selected += 15

        # Tab-specific keys
        if self.tab == 0:   # AI Observer
            if event.key == pygame.K_s:
                self.show_sidebar = not self.show_sidebar
        elif self.tab == 1: # ECS Browser
            if event.key == pygame.K_TAB:
                self.filter_idx = (self.filter_idx + 1) % len(_FILTER_CATS)
                self.selected = 0
            elif event.key == pygame.K_RETURN:
                eids = self._filtered_eids(app)
                if 0 <= self.selected < len(eids):
                    eid = eids[self.selected]
                    self.expanded.symmetric_difference_update({eid})
        elif self.tab == 2: # Entity Editor
            if event.key == pygame.K_RETURN:
                self._start_edit(app)
            elif event.key == pygame.K_LEFT:
                self.edit_field_idx = max(0, self.edit_field_idx - 1)
            elif event.key == pygame.K_RIGHT:
                self.edit_field_idx += 1
        elif self.tab == 3: # Event Log
            if event.key == pygame.K_c:
                log = app.world.res(DevLog)
                if log:
                    log.clear()
            elif event.key == pygame.K_TAB:
                cats = ["", "combat", "attack", "brain", "error", "move", "need", "system", "edit"]
                idx = cats.index(self.log_cat_filter) if self.log_cat_filter in cats else 0
                self.log_cat_filter = cats[(idx + 1) % len(cats)]

    def update(self, dt: float, app: App):
        pass

    # ── filtering for ECS tab ────────────────────────────────────────

    def _filtered_eids(self, app: App) -> list[int]:
        dump = app.world.debug_dump()
        cat = _FILTER_CATS[self.filter_idx]
        eids: list[int] = []
        for eid in sorted(dump.keys()):
            if eid == -1:
                if cat in ("All", "Resources"):
                    eids.append(eid)
                continue
            ctypes = {type(c).__name__ for c in dump[eid]}
            if cat == "All":
                eids.append(eid)
            elif cat == "NPCs" and ("Brain" in ctypes or "Faction" in ctypes):
                eids.append(eid)
            elif cat == "Combat" and ctypes & {"Threat", "AttackConfig", "Projectile"}:
                eids.append(eid)
            elif cat == "Items" and ctypes & {"Inventory", "Loot", "LootTableRef"}:
                eids.append(eid)
            elif cat == "Resources" and eid == -1:
                eids.append(eid)
        return eids

    # ── NPC list for AI tab ──────────────────────────────────────────

    def _npc_list(self, app):
        from components import Brain, Faction, Health, Hunger, Identity, Position, Lod
        entries = []
        for eid, brain in app.world.all_of(Brain):
            ident = app.world.get(eid, Identity)
            name = ident.name if ident else f"e{eid}"
            faction = app.world.get(eid, Faction)
            fac = f"{faction.group}/{faction.disposition}" if faction else "-"
            active = brain.active
            combat = brain.state.get("combat", {})
            if combat:
                mode = combat.get("mode", "?")
                los = combat.get("_los_blocked", False)
            else:
                v = brain.state.get("villager", {})
                mode = f"v:{v.get('mode', '?')}" if v else "-"
                los = False
            hp = app.world.get(eid, Health)
            hp_str = f"{hp.current:.0f}/{hp.maximum:.0f}" if hp else "-"
            hunger = app.world.get(eid, Hunger)
            hng_str = f"{hunger.current:.0f}" if hunger else "-"
            pos = app.world.get(eid, Position)
            pos_str = f"({pos.x:.1f},{pos.y:.1f})" if pos else "-"
            lod = app.world.get(eid, Lod)
            lod_str = lod.level[0].upper() if lod else "?"
            entries.append({
                "eid": eid, "name": name, "fac": fac, "active": active,
                "mode": mode, "los": los, "hp": hp_str, "hng": hng_str,
                "pos": pos_str, "lod": lod_str, "brain": brain,
            })
        return entries

    # ── editor helpers ───────────────────────────────────────────────

    def _editable_fields(self, app) -> list[tuple[str, str, str]]:
        """Return [(key, type_hint, current_val), ...] for edit_eid."""
        if self.edit_eid is None:
            return []
        dump = app.world.debug_dump()
        comps = dump.get(self.edit_eid, [])
        fields: list[tuple[str, str, str]] = []
        for comp in comps:
            cname = type(comp).__name__
            if hasattr(comp, '__dataclass_fields__'):
                for f in dc_fields(comp):
                    val = getattr(comp, f.name)
                    if isinstance(val, (float, int, str, bool)):
                        key = f"{cname}.{f.name}"
                        fields.append((key, type(val).__name__, _fmt(val, 60)))
        return fields

    def _start_edit(self, app):
        """Begin editing the currently selected field."""
        if self.tab == 2:
            npcs = self._npc_list(app)
            if 0 <= self.selected < len(npcs):
                self.edit_eid = npcs[self.selected]["eid"]
            fl = self._editable_fields(app)
            if fl and 0 <= self.edit_field_idx < len(fl):
                self.edit_value = fl[self.edit_field_idx][2]
                self.editing = True

    def _apply_edit(self, app):
        """Apply a text edit to a component field."""
        if self.edit_eid is None:
            return
        fl = self._editable_fields(app)
        if not fl or self.edit_field_idx >= len(fl):
            return
        key = fl[self.edit_field_idx][0]
        parts = key.split(".", 1)
        if len(parts) != 2:
            return
        comp_name, field_name = parts
        dump = app.world.debug_dump()
        comps = dump.get(self.edit_eid, [])
        for comp in comps:
            if type(comp).__name__ == comp_name:
                if hasattr(comp, field_name):
                    old_val = getattr(comp, field_name)
                    try:
                        if isinstance(old_val, float):
                            setattr(comp, field_name, float(self.edit_value))
                        elif isinstance(old_val, int):
                            setattr(comp, field_name, int(self.edit_value))
                        elif isinstance(old_val, bool):
                            setattr(comp, field_name, self.edit_value.lower() in ("true", "1", "yes"))
                        elif isinstance(old_val, str):
                            setattr(comp, field_name, self.edit_value)
                        log = app.world.res(DevLog)
                        if log:
                            from components import Identity
                            ident = app.world.get(self.edit_eid, Identity)
                            nm = ident.name if ident else f"e{self.edit_eid}"
                            log.record(self.edit_eid, "edit",
                                       f"{comp_name}.{field_name} = {self.edit_value}",
                                       name=nm, t=0.0)
                    except (ValueError, TypeError):
                        pass
                break

    # ── draw ─────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, app: App):
        surface.fill(_BG)
        sw, sh = surface.get_size()

        # ── Tab bar ──────────────────────────────────────────────────
        tab_y = 6
        tx = 10
        for i, tname in enumerate(_TAB_NAMES):
            color = _HEADER if i == self.tab else _DIM
            label = f"[{i+1}] {tname}"
            r = app.draw_text(surface, label, tx, tab_y, color, app.font)
            tx += r.width + 16
        # Key legend
        app.draw_text(surface, "[Esc] close", sw - 100, tab_y, _DIM, app.font_sm)
        # Separator
        pygame.draw.line(surface, _BORDER, (0, 26), (sw, 26), 1)

        body_y = 30
        body_h = sh - body_y

        if self.tab == 0:
            self._draw_ai_observer(surface, app, body_y, sw, body_h)
        elif self.tab == 1:
            self._draw_ecs_browser(surface, app, body_y, sw, body_h)
        elif self.tab == 2:
            self._draw_entity_editor(surface, app, body_y, sw, body_h)
        elif self.tab == 3:
            self._draw_event_log(surface, app, body_y, sw, body_h)

    # ── TAB 0: AI Observer ───────────────────────────────────────────

    def _draw_ai_observer(self, surface, app, top, sw, sh):
        from components import GameClock, Threat, AttackConfig
        from components.ai import HomeRange

        npcs = self._npc_list(app)
        if npcs:
            self.selected = min(self.selected, len(npcs) - 1)

        clock = app.world.res(GameClock)
        clock_t = clock.time if clock else 0.0

        sidebar_w = sw // 3 if self.show_sidebar else 0
        table_w = sw - sidebar_w - 4

        # ── NPC table ────────────────────────────────────────────────
        y = top + 4
        app.draw_text(surface, f"NPCs: {len(npcs)}  Clock: {clock_t:.1f}s  [S] sidebar  [Up/Dn] select",
                      10, y, _SUBHEADER, app.font_sm)
        y += 16

        # Header row
        hdr = f"{'ID':>3} {'Name':>10} {'Faction':>14} {'A':>1} {'Mode':>8} {'HP':>7} {'Hng':>4} {'Pos':>13} {'L':>1}"
        app.draw_text(surface, hdr, 10, y, (80, 140, 120), app.font_sm)
        y += 13
        pygame.draw.line(surface, _BORDER, (8, y), (table_w, y), 1)
        y += 3

        for idx, npc in enumerate(npcs):
            if y > top + sh - 14:
                app.draw_text(surface, f"  +{len(npcs) - idx} more...", 10, y, _DIM, app.font_sm)
                break
            is_sel = idx == self.selected
            if is_sel:
                pygame.draw.rect(surface, _HIGHLIGHT_BG, (6, y - 1, table_w - 4, 13))

            mode_base = npc["mode"].rstrip("*").split(":")[-1]
            mode_c = _MODE_COLORS.get(mode_base, _TEXT)
            act = "●" if npc["active"] else "○"
            los_mark = "!" if npc["los"] else ""
            row = (f"{npc['eid']:>3} {npc['name']:>10} {npc['fac']:>14} "
                   f"{act:>1} {npc['mode']+los_mark:>8} {npc['hp']:>7} "
                   f"{npc['hng']:>4} {npc['pos']:>13} {npc['lod']:>1}")
            color = (0, 255, 150) if is_sel else mode_c
            app.draw_text(surface, row, 10, y, color, app.font_sm)
            y += 13

        # ── Sidebar: selected NPC detail + action log ────────────────
        if self.show_sidebar and npcs:
            px = sw - sidebar_w + 8
            pygame.draw.line(surface, _BORDER, (px - 6, top), (px - 6, top + sh), 1)

            sel_npc = npcs[self.selected] if 0 <= self.selected < len(npcs) else None
            if sel_npc is None:
                return

            py = top + 4
            app.draw_text(surface, f"DETAIL: {sel_npc['name']} (e{sel_npc['eid']})",
                          px, py, _HEADER, app.font)
            py += 20

            brain = sel_npc["brain"]
            app.draw_text(surface, f"Brain: {brain.kind}  active: {brain.active}",
                          px, py, (180, 220, 255), app.font_sm)
            py += 13

            # Full brain.state dump
            state_limit = top + sh * 2 // 3
            for sk, sv in brain.state.items():
                if py > state_limit:
                    app.draw_text(surface, "  ...", px, py, _DIM, app.font_sm)
                    py += 12
                    break
                if isinstance(sv, dict):
                    app.draw_text(surface, f"  {sk}:", px, py, (120, 200, 255), app.font_sm)
                    py += 12
                    for dk, dv in sv.items():
                        if py > state_limit:
                            break
                        dv_s = _fmt(dv, 35)
                        app.draw_text(surface, f"    {dk}: {dv_s}", px, py, (170, 170, 140), app.font_sm)
                        py += 11
                else:
                    app.draw_text(surface, f"  {sk}: {_fmt(sv, 40)}", px, py, (170, 170, 140), app.font_sm)
                    py += 12

            # Threat/Attack
            eid = sel_npc["eid"]
            threat = app.world.get(eid, Threat)
            atk = app.world.get(eid, AttackConfig)
            if threat:
                py += 4
                app.draw_text(surface,
                    f"Threat: aggro={threat.aggro_radius:.0f} "
                    f"leash={threat.leash_radius:.0f} "
                    f"flee={threat.flee_threshold:.0%}",
                    px, py, (200, 160, 120), app.font_sm)
                py += 12
            if atk:
                app.draw_text(surface,
                    f"Attack: {atk.attack_type} rng={atk.range:.1f} "
                    f"cd={atk.cooldown:.2f} last={atk.last_attack_time:.1f}",
                    px, py, (200, 160, 120), app.font_sm)
                py += 12
            patrol = app.world.get(eid, HomeRange)
            if patrol:
                app.draw_text(surface,
                    f"HomeRange: o=({patrol.origin_x:.1f},{patrol.origin_y:.1f}) "
                    f"r={patrol.radius:.1f} spd={patrol.speed:.1f}",
                    px, py, (160, 200, 160), app.font_sm)
                py += 12

            # ── Action log for this entity ───────────────────────────
            py += 8
            pygame.draw.line(surface, _BORDER, (px, py), (sw - 8, py), 1)
            py += 4
            app.draw_text(surface, f"ACTION LOG (e{eid})", px, py, (200, 180, 100), app.font_sm)
            py += 14

            log = app.world.res(DevLog)
            if log:
                entries = log.for_eid(eid, n=30)
                for entry in reversed(entries):
                    if py > top + sh - 14:
                        break
                    cat = entry.get("cat", "?")
                    msg = entry.get("msg", "")
                    t = entry.get("t", 0.0)
                    cat_c = _CAT_COLORS.get(cat, _TEXT)
                    app.draw_text(surface, f"{t:7.1f} [{cat:>6}] {msg}",
                                  px, py, cat_c, app.font_sm)
                    py += 11
            else:
                app.draw_text(surface, "(no DevLog resource)", px, py, _DIM, app.font_sm)

    # ── TAB 1: ECS Browser ───────────────────────────────────────────

    def _draw_ecs_browser(self, surface, app, top, sw, sh):
        dump = app.world.debug_dump()
        eids = self._filtered_eids(app)
        if eids:
            self.selected = min(self.selected, len(eids) - 1)
        else:
            self.selected = 0

        y = top + 4
        filt = _FILTER_CATS[self.filter_idx]
        app.draw_text(surface,
            f"Entities: {len(eids)}  Filter: [{filt}]  "
            f"[Tab] cycle  [Enter] expand  [PgUp/Dn] scroll",
            10, y, _SUBHEADER, app.font_sm)
        y += 16
        max_chars = sw // 7

        for idx, eid in enumerate(eids):
            if y > top + sh - 14:
                app.draw_text(surface, f"  ... +{len(eids) - idx} more",
                              10, y, _DIM, app.font_sm)
                break

            comps = dump.get(eid, [])
            is_sel = idx == self.selected
            is_exp = eid in self.expanded

            name = None
            for c in comps:
                if type(c).__name__ == "Identity":
                    name = c.name
                    break

            prefix = "▼" if is_exp else "▶"
            if is_sel:
                pygame.draw.rect(surface, _HIGHLIGHT_BG, (6, y - 1, sw - 12, 14))
            header_c = (0, 255, 150) if is_sel else (180, 180, 180)

            comp_names = ", ".join(type(c).__name__ for c in comps)
            label = f"{prefix} e{eid}"
            if name:
                label += f" [{name}]"
            label += f": {comp_names}"
            if len(label) > max_chars:
                label = label[:max_chars - 3] + "..."
            app.draw_text(surface, label, 10, y, header_c, app.font_sm)
            y += 14

            if is_exp:
                for comp in comps:
                    if y > top + sh - 14:
                        break
                    cname = type(comp).__name__
                    cc = _COMP_COLORS.get(cname, _TEXT)
                    app.draw_text(surface, f"    {cname}:", 10, y, cc, app.font_sm)
                    y += 12
                    if hasattr(comp, '__dataclass_fields__'):
                        for f in dc_fields(comp):
                            if y > top + sh - 14:
                                break
                            val = getattr(comp, f.name)
                            vs = _fmt(val, max_chars - 14)
                            app.draw_text(surface, f"      {f.name}: {vs}",
                                          10, y, _TEXT, app.font_sm)
                            y += 11
                            if isinstance(val, dict) and val:
                                for dk, dv in list(val.items())[:8]:
                                    if y > top + sh - 14:
                                        break
                                    app.draw_text(surface,
                                        f"        {dk}: {_fmt(dv, 35)}",
                                        10, y, (170, 170, 140), app.font_sm)
                                    y += 10
                    else:
                        s = str(comp)
                        if len(s) > max_chars - 10:
                            s = s[:max_chars - 13] + "..."
                        app.draw_text(surface, f"      {s}", 10, y, _TEXT, app.font_sm)
                        y += 11

    # ── TAB 2: Entity Editor ─────────────────────────────────────────

    def _draw_entity_editor(self, surface, app, top, sw, sh):
        npcs = self._npc_list(app)
        if npcs:
            self.selected = min(self.selected, len(npcs) - 1)

        y = top + 4
        app.draw_text(surface,
            "ENTITY EDITOR  [Up/Dn] NPC  [Left/Right] field  [Enter] edit  type value + Enter",
            10, y, _SUBHEADER, app.font_sm)
        y += 18

        # Left: NPC list
        left_w = sw // 3
        ly = y
        for idx, npc in enumerate(npcs):
            if ly > top + sh - 14:
                break
            is_sel = idx == self.selected
            if is_sel:
                pygame.draw.rect(surface, _HIGHLIGHT_BG, (6, ly - 1, left_w - 8, 13))
            color = (0, 255, 150) if is_sel else _TEXT
            app.draw_text(surface,
                f"e{npc['eid']:>3} {npc['name']:>12} {npc['mode']:>8}",
                10, ly, color, app.font_sm)
            ly += 13

        # Right: selected entity's editable fields
        sel_npc = npcs[self.selected] if npcs and 0 <= self.selected < len(npcs) else None
        if sel_npc is None:
            return

        rx = left_w + 10
        ry = y
        eid = sel_npc["eid"]
        self.edit_eid = eid

        app.draw_text(surface, f"Editing: {sel_npc['name']} (e{eid})",
                      rx, ry, _HEADER, app.font)
        ry += 20

        fl = self._editable_fields(app)
        if fl:
            self.edit_field_idx = min(self.edit_field_idx, len(fl) - 1)

        for i, (key, tname, cur_val) in enumerate(fl):
            if ry > top + sh - 14:
                break
            is_field_sel = i == self.edit_field_idx
            is_editing_this = self.editing and is_field_sel
            if is_field_sel:
                marker = "▸" if not self.editing else "✎"
                pygame.draw.rect(surface, (40, 45, 35), (rx - 2, ry - 1, sw - rx - 8, 12))
            else:
                marker = " "

            if is_editing_this:
                pygame.draw.rect(surface, (50, 40, 30), (rx - 2, ry - 1, sw - rx - 8, 12))
                display_val = self.edit_value + "█"
                app.draw_text(surface,
                    f"{marker} {key} ({tname}) = {display_val}",
                    rx, ry, (255, 220, 100), app.font_sm)
            else:
                cv = cur_val if len(cur_val) < 50 else cur_val[:47] + "..."
                color = (220, 220, 200) if is_field_sel else _TEXT
                app.draw_text(surface,
                    f"{marker} {key} ({tname}) = {cv}",
                    rx, ry, color, app.font_sm)
            ry += 12

        if not fl:
            app.draw_text(surface, "(no editable scalar fields)", rx, ry, _DIM, app.font_sm)

    # ── TAB 3: Event Log ─────────────────────────────────────────────

    def _draw_event_log(self, surface, app, top, sw, sh):
        log = app.world.res(DevLog)

        y = top + 4
        cat_str = self.log_cat_filter or "all"
        count = len(log.entries) if log else 0
        app.draw_text(surface,
            f"EVENT LOG — {count} entries  filter:[{cat_str}]  "
            f"[Tab] filter  [C] clear  [PgUp/Dn] scroll",
            10, y, _SUBHEADER, app.font_sm)
        y += 16

        if not log or not log.entries:
            app.draw_text(surface,
                "(no events recorded yet — play the game with NPCs active)",
                10, y, _DIM, app.font_sm)
            return

        # Filter entries
        if self.log_cat_filter:
            entries = [e for e in log.entries if e.get("cat") == self.log_cat_filter]
        else:
            entries = list(log.entries)

        # Scroll
        max_visible = (sh - 20) // 12
        total = len(entries)
        self.log_scroll = min(self.log_scroll, max(0, total - max_visible))
        start = max(0, total - max_visible - self.log_scroll)
        end = start + max_visible
        visible = entries[start:end]

        for entry in visible:
            if y > top + sh - 14:
                break
            t = entry.get("t", 0.0)
            eid = entry.get("eid", "?")
            name = entry.get("name", "?")
            cat = entry.get("cat", "?")
            msg = entry.get("msg", "")
            cat_c = _CAT_COLORS.get(cat, _TEXT)
            line = f"{t:7.1f}  e{eid:<3} {name:>10}  [{cat:>6}]  {msg}"
            max_chars = sw // 7
            if len(line) > max_chars:
                line = line[:max_chars - 3] + "..."
            app.draw_text(surface, line, 10, y, cat_c, app.font_sm)
            y += 12

        # Scroll indicator
        if total > max_visible:
            pct = (total - self.log_scroll - max_visible) / max(1, total) * 100
            app.draw_text(surface, f"scroll: {pct:.0f}%  ({total} total)",
                          sw - 200, top + sh - 14, _DIM, app.font_sm)


# ── helpers ──────────────────────────────────────────────────────────

def _fmt(val, max_len: int = 50) -> str:
    if isinstance(val, float):
        return f"{val:.2f}"
    if isinstance(val, dict):
        if not val:
            return "{}"
        items = [f"{k}: {_fmt(v, 15)}" for k, v in list(val.items())[:5]]
        s = "{" + ", ".join(items) + "}"
        if len(val) > 5:
            s += f" +{len(val)-5}"
        return s
    s = str(val)
    return s if len(s) <= max_len else s[:max_len - 3] + "..."
