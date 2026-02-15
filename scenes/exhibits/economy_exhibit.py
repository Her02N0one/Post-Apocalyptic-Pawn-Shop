"""scenes/exhibits/economy_exhibit.py — Settlement Economy exhibit.

Demonstrates the communal Stockpile system: a settlement entity holds
shared resources.  NPCs deposit items into the stockpile and withdraw
food when hungry.  The ``settlement_needs`` query shows what the
village is short on.

Layout
------
Centre  — settlement stockpile display (items + totals)
Left    — Farmer NPC with food to deposit
Right   — Hungry NPC who needs to withdraw
Bottom  — event log of deposits/withdrawals

Controls:
    Space — cycle: deposit → withdraw → check needs → reset
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from scenes.exhibits.base import Exhibit
from core.constants import TILE_SIZE
from components import (
    Position, Velocity, Sprite, Identity, Collider,
    Facing, Health, CombatStats, Lod, Brain, GameClock,
    Hunger, Inventory,
)
from components.ai import HomeRange
from components.social import Faction
from components.simulation import SubzonePos, Home, Stockpile
from simulation.economy import (
    create_settlement, deposit_to_stockpile,
    withdraw_from_stockpile, settlement_needs,
    get_settlement_stockpile,
)

if TYPE_CHECKING:
    import pygame
    from core.app import App


class EconomyExhibit(Exhibit):
    """Economy — settlement stockpile deposit / withdraw / needs."""

    name = "Economy"
    category = "Simulation"
    description = (
        "Settlement Stockpile Economy\n"
        "\n"
        "A settlement entity holds communal resources in a\n"
        "Stockpile component.  NPCs deposit harvested items\n"
        "and withdraw food when hungry.  The settlement_needs\n"
        "query shows what the village is short on.\n"
        "\n"
        "Cycle through phases:\n"
        " 1. DEPOSIT:  Farmer adds raw_food and corn\n"
        " 2. WITHDRAW: Hungry NPC takes food from stockpile\n"
        " 3. NEEDS:    Query what the settlement still needs\n"
        "\n"
        "What to observe:\n"
        " - Stockpile item counts change with each phase\n"
        " - Individual NPC inventories update accordingly\n"
        " - Needs assessment identifies low supplies\n"
        "\n"
        "Systems:  deposit_to_stockpile  withdraw_from_stockpile\n"
        "          settlement_needs  Stockpile\n"
        "Controls: [Space] cycle: deposit -> withdraw -> needs -> reset"
    )
    default_debug = {"brain": True}

    def __init__(self):
        self._settlement_eid: int = 0
        self._farmer_eid: int = 0
        self._hungry_eid: int = 0
        self._phase = "ready"  # ready → deposited → withdrawn → needs
        self._log: list[str] = []

    def setup(self, app, zone, tiles):
        eids: list[int] = []
        self._phase = "ready"
        self._log = ["Press [Space] to deposit food"]
        w = app.world

        # Create settlement entity with a stockpile
        # (Using SubzonePos so economy queries find it)
        s_eid = w.spawn()
        w.add(s_eid, Identity(name="Haven", kind="settlement"))
        w.add(s_eid, SubzonePos(zone=zone, subzone="haven_centre"))
        w.add(s_eid, Stockpile(items={"raw_food": 3, "bandage": 1}))
        w.add(s_eid, Position(x=15.0, y=8.0, zone=zone))
        w.add(s_eid, Sprite(char="S", color=(220, 180, 60)))
        w.zone_add(s_eid, zone)
        self._settlement_eid = s_eid
        eids.append(s_eid)

        # Farmer — carries food to deposit
        f_eid = self._spawn_npc(app, zone, "Farmer Joe", 6.0, 10.0,
                                color=(120, 200, 80))
        w.add(f_eid, Inventory(items={"raw_food": 5, "corn": 3}))
        w.add(f_eid, Home(zone=zone, subzone="haven_centre"))
        self._farmer_eid = f_eid
        eids.append(f_eid)

        # Hungry NPC — needs to withdraw
        h_eid = self._spawn_npc(app, zone, "Hungry Mara", 24.0, 10.0,
                                color=(200, 100, 100))
        w.add(h_eid, Inventory(items={}))
        w.add(h_eid, Hunger(current=20.0, maximum=100.0, rate=0.5))
        w.add(h_eid, Home(zone=zone, subzone="haven_centre"))
        self._hungry_eid = h_eid
        eids.append(h_eid)

        return eids

    def _spawn_npc(self, app, zone, name, x, y, *, color):
        w = app.world
        eid = w.spawn()
        w.add(eid, Position(x=x, y=y, zone=zone))
        w.add(eid, Velocity())
        w.add(eid, Sprite(char=name[0], color=color))
        w.add(eid, Identity(name=name, kind="npc"))
        w.add(eid, Collider())
        w.add(eid, Facing())
        w.add(eid, Health(current=100, maximum=100))
        w.add(eid, CombatStats(damage=5, defense=2))
        w.add(eid, Lod(level="high"))
        w.add(eid, Brain(kind="villager", active=True))
        w.add(eid, HomeRange(origin_x=x, origin_y=y, radius=4.0, speed=1.5))
        w.add(eid, Faction(group="settlers", disposition="neutral",
                           home_disposition="neutral"))
        w.zone_add(eid, zone)
        return eid

    def on_space(self, app):
        if self._phase == "ready":
            self._do_deposit(app)
            return None
        elif self._phase == "deposited":
            self._do_withdraw(app)
            return None
        elif self._phase == "withdrawn":
            self._do_needs_check(app)
            return None
        else:
            return "reset"

    def _do_deposit(self, app):
        w = app.world
        deposited_food = deposit_to_stockpile(w, self._farmer_eid, "raw_food", 5)
        deposited_corn = deposit_to_stockpile(w, self._farmer_eid, "corn", 3)

        stockpile = w.get(self._settlement_eid, Stockpile)
        inv = w.get(self._farmer_eid, Inventory)

        self._log = [
            "--- DEPOSIT ---",
            f"Farmer deposited {deposited_food}x raw_food",
            f"Farmer deposited {deposited_corn}x corn",
            f"Farmer inventory: {dict(inv.items) if inv else {}}",
            f"Stockpile: {dict(stockpile.items) if stockpile else {}}",
            f"Stockpile total: {stockpile.total_count() if stockpile else 0}",
        ]
        self._phase = "deposited"

    def _do_withdraw(self, app):
        w = app.world
        withdrawn = withdraw_from_stockpile(w, self._hungry_eid, "raw_food", 2)

        stockpile = w.get(self._settlement_eid, Stockpile)
        inv = w.get(self._hungry_eid, Inventory)

        self._log.append("")
        self._log.append("--- WITHDRAW ---")
        self._log.append(f"Hungry Mara withdrew {withdrawn}x raw_food")
        self._log.append(f"Mara inventory: {dict(inv.items) if inv else {}}")
        self._log.append(f"Stockpile: {dict(stockpile.items) if stockpile else {}}")
        self._phase = "withdrawn"

    def _do_needs_check(self, app):
        w = app.world
        # Use direct stockpile query
        stockpile = w.get(self._settlement_eid, Stockpile)
        needs = {}
        if stockpile:
            food_count = sum(v for k, v in stockpile.items.items()
                            if "food" in k or "corn" in k)
            if food_count < 10:
                needs["food"] = 10 - food_count

        self._log.append("")
        self._log.append("--- NEEDS ASSESSMENT ---")
        if needs:
            for item, qty in needs.items():
                self._log.append(f"  Need {qty}x {item}")
        else:
            self._log.append("  Settlement is well-supplied!")
        self._phase = "needs"

    def update(self, app, dt, tiles, eids):
        pass

    def draw(self, surface, ox, oy, app, eids, tile_px=TILE_SIZE, flags=None):
        import pygame
        w = app.world

        # Stockpile display
        stockpile = w.get(self._settlement_eid, Stockpile)
        panel_x = ox + 10 * tile_px
        py = oy + 2 * tile_px
        app.draw_text(surface, "SETTLEMENT STOCKPILE", panel_x, py,
                      (220, 180, 60), app.font_sm)
        py += 18
        if stockpile:
            for item_id, count in sorted(stockpile.items.items()):
                app.draw_text(surface, f"  {item_id}: {count}", panel_x, py,
                              (180, 180, 140), app.font_sm)
                py += 14
            py += 4
            app.draw_text(surface, f"  Total: {stockpile.total_count()}",
                          panel_x, py, (200, 200, 160), app.font_sm)
        else:
            app.draw_text(surface, "  (empty)", panel_x, py,
                          (120, 120, 120), app.font_sm)

        # Inventory displays
        for eid, label, lx in [
            (self._farmer_eid, "Farmer", 2),
            (self._hungry_eid, "Hungry", 22),
        ]:
            inv = w.get(eid, Inventory)
            ix = ox + lx * tile_px
            iy = oy + 4 * tile_px
            app.draw_text(surface, label, ix, iy, (160, 160, 160), app.font_sm)
            iy += 14
            if inv and inv.items:
                for item, count in inv.items.items():
                    app.draw_text(surface, f"  {item}:{count}", ix, iy,
                                  (140, 140, 140), app.font_sm)
                    iy += 13
            else:
                app.draw_text(surface, "  (empty)", ix, iy,
                              (100, 100, 100), app.font_sm)

        # Event log
        log_x = ox + 2 * tile_px
        ly = oy + 13 * tile_px
        for line in self._log[-8:]:
            app.draw_text(surface, line, log_x, ly,
                          (180, 180, 180), app.font_sm)
            ly += 14

    def info_text(self, app, eids):
        phases = {
            "ready": "[Space] Deposit  |  Farmer deposits food → stockpile",
            "deposited": "[Space] Withdraw  |  Hungry NPC takes food",
            "withdrawn": "[Space] Check Needs  |  Settlement needs assessment",
            "needs": "[Space] Reset  |  Economy cycle complete",
        }
        return phases.get(self._phase, "")
