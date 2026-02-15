"""scenes/exhibits/stat_combat_exhibit.py — Off-Screen Stat Combat exhibit.

Demonstrates how combat resolves for entities in unloaded zones.
Two hostile NPCs are placed at the same subzone node and their
encounter resolves via ``stat_check_combat`` — a deterministic DPS
race with flee checks and variance.

Layout
------
Left side  — two NPC portraits with health bars
Right side — combat log showing DPS, TTK, flee checks, and outcome

Controls:
    Space — run one combat resolution → show result → reset
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from scenes.exhibits.base import Exhibit
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider, Hurtbox,
    Facing, Health, CombatStats, Lod, Brain, GameClock, Inventory,
)
from components.ai import HomeRange, Threat, AttackConfig
from components.social import Faction
from components.simulation import SubzonePos, Home
from simulation.stat_combat import stat_check_combat, CombatResult

if TYPE_CHECKING:
    import pygame
    from core.app import App


class StatCombatExhibit(Exhibit):
    """Stat Combat — off-screen DPS-race resolution."""

    name = "Stat Combat"
    category = "Combat"
    description = (
        "Off-Screen Stat Combat\n"
        "\n"
        "When two hostile NPCs meet in an unloaded zone,\n"
        "combat resolves via stat_check_combat — a DPS race\n"
        "with flee checks and damage variance.  No real-time\n"
        "simulation; it's instant deterministic resolution.\n"
        "\n"
        "Two fighters:\n"
        " Guard Brock (blue) — HP:100  DMG:12  DEF:6  flee:20%\n"
        " Raider Vex  (red)  — HP:80   DMG:15  DEF:3  flee:35%\n"
        "\n"
        "What to observe:\n"
        " - DPS calculation:  damage * (1 - def/100) / cooldown\n"
        " - Flee check: loser flees when HP < flee_threshold %\n"
        " - Fight duration in game-minutes\n"
        " - Winner's remaining HP after the fight\n"
        "\n"
        "Systems:  stat_check_combat  CombatResult\n"
        "Controls: [Space] resolve combat / reset"
    )
    default_debug = {"health": True}

    def __init__(self):
        self._result: CombatResult | None = None
        self._fighter_a: int = 0
        self._fighter_b: int = 0
        self._log: list[str] = []
        self._resolved = False

    def setup(self, app, zone, tiles):
        eids: list[int] = []
        self._result = None
        self._log = ["Press [Space] to resolve combat"]
        self._resolved = False

        # Fighter A — well-equipped guard
        a = self._spawn_fighter(
            app, zone, "Guard Brock", 8.0, 9.0,
            color=(80, 160, 255),
            hp=100, damage=12, defense=6,
            faction_group="settlers", disposition="hostile",
            flee_threshold=0.2, speed=2.0,
        )
        inv_a = Inventory(items={"combat_knife": 1, "bandage": 2})
        app.world.add(a, inv_a)
        self._fighter_a = a
        eids.append(a)

        # Fighter B — aggressive raider
        b = self._spawn_fighter(
            app, zone, "Raider Vex", 18.0, 9.0,
            color=(255, 80, 80),
            hp=80, damage=15, defense=3,
            faction_group="raiders", disposition="hostile",
            flee_threshold=0.35, speed=2.5,
        )
        inv_b = Inventory(items={"pipe_pistol": 1})
        app.world.add(b, inv_b)
        self._fighter_b = b
        eids.append(b)

        return eids

    def _spawn_fighter(self, app, zone, name, x, y, *,
                       color, hp, damage, defense,
                       faction_group, disposition,
                       flee_threshold, speed):
        w = app.world
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=color))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Hurtbox())
        w.add(eid, Facing())
        w.add(eid, Health(current=hp, maximum=hp))
        w.add(eid, CombatStats(damage=damage, defense=defense))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind="hostile_melee", active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=6.0, speed=speed))
        w.add(eid, Faction(group=faction_group, disposition=disposition,
                           home_disposition=disposition))
        w.add(eid, Threat(aggro_radius=5000.0, leash_radius=200.0,
                          flee_threshold=flee_threshold))
        w.add(eid, AttackConfig(attack_type="melee", range=1.2, cooldown=0.5))
        w.zone_add(eid, zone)
        return eid

    def on_space(self, app):
        if self._resolved:
            return "reset"
        self._resolve_combat(app)
        return None

    def _resolve_combat(self, app):
        w = app.world
        a, b = self._fighter_a, self._fighter_b

        # Log pre-combat stats
        hp_a = w.get(a, Health)
        hp_b = w.get(b, Health)
        cs_a = w.get(a, CombatStats)
        cs_b = w.get(b, CombatStats)
        id_a = w.get(a, Identity)
        id_b = w.get(b, Identity)
        na = id_a.name if id_a else "A"
        nb = id_b.name if id_b else "B"

        self._log = [
            f"--- {na} vs {nb} ---",
            f"{na}: HP={hp_a.current:.0f}/{hp_a.maximum:.0f} HP  "
            f"DMG={cs_a.damage:.0f} HP  DEF={cs_a.defense:.0f}",
            f"{nb}: HP={hp_b.current:.0f}/{hp_b.maximum:.0f} HP  "
            f"DMG={cs_b.damage:.0f} HP  DEF={cs_b.defense:.0f}",
            "",
        ]

        result = stat_check_combat(w, a, b)
        self._result = result

        w_ident = w.get(result.winner_eid, Identity)
        l_ident = w.get(result.loser_eid, Identity)
        wn = w_ident.name if w_ident else "?"
        ln = l_ident.name if l_ident else "?"

        if result.loser_fled:
            self._log.append(f"RESULT: {ln} FLED after {result.fight_duration:.1f} min")
        else:
            self._log.append(f"RESULT: {wn} WINS in {result.fight_duration:.1f} min")
            self._log.append(f"  {ln} killed")

        self._log.append(f"  Winner took {result.winner_damage_taken:.0f} HP dmg")

        hp_a2 = w.get(a, Health)
        hp_b2 = w.get(b, Health)
        self._log.append(f"Post: {na} HP={hp_a2.current:.0f} HP  "
                         f"{nb} HP={hp_b2.current:.0f} HP")

        self._resolved = True

    def update(self, app, dt, tiles, eids):
        pass

    def draw(self, surface, ox, oy, app, eids, tile_px=TILE_SIZE, flags=None):
        import pygame
        w = app.world

        # Draw VS label
        app.draw_text(surface, "VS", ox + 13 * tile_px, oy + 8 * tile_px,
                      (255, 255, 80), app.font_lg)

        # Draw big health bars for each fighter
        for eid, bx in [(self._fighter_a, 4), (self._fighter_b, 16)]:
            if not w.alive(eid):
                continue
            hp = w.get(eid, Health)
            ident = w.get(eid, Identity)
            if not hp:
                continue
            bar_x = ox + bx * tile_px
            bar_y = oy + 14 * tile_px
            bar_w = 6 * tile_px
            ratio = max(0.0, hp.current / hp.maximum)
            pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, 10))
            bc = ((50, 200, 50) if ratio > 0.5
                  else (220, 200, 50) if ratio > 0.25
                  else (220, 50, 50))
            pygame.draw.rect(surface, bc,
                             (bar_x, bar_y, max(1, int(bar_w * ratio)), 10))
            label = f"{hp.current:.0f}/{hp.maximum:.0f} HP"
            app.draw_text(surface, label, bar_x, bar_y + 12,
                          (180, 180, 180), app.font_sm)

        # Combat log panel
        panel_x = ox + 2 * tile_px
        py = oy + 2 * tile_px
        app.draw_text(surface, "STAT COMBAT", panel_x, py,
                      (255, 200, 80), app.font_sm)
        py += 18
        for line in self._log:
            app.draw_text(surface, line, panel_x, py,
                          (180, 180, 180), app.font_sm)
            py += 14

    def info_text(self, app, eids):
        if self._resolved:
            return "[Space] Reset  |  Off-screen combat resolved via stat check"
        return "[Space] Resolve Combat  |  DPS race with flee checks"
