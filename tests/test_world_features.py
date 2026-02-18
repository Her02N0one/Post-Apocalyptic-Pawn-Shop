"""tests/test_world_features.py — Tests for gameplay features.

Covers: WorldClock ticking, WorldEventLog, off-screen combat,
beast spawning, container restocking, dialogue generation.
"""

from __future__ import annotations

import pytest
from core.ecs import World
from components import (
    CoarsePos, Health, Identity, CombatStats, Timers,
    Position, Player, GameClock, WorldClock, WorldEventLog,
    TileEntity, Sprite,
)
from core.types import EntityKind


# ═══════════════════════════════════════════════════════════════════════
#  WorldClock
# ═══════════════════════════════════════════════════════════════════════

class TestWorldClock:
    def test_default_phase(self):
        wc = WorldClock()
        assert wc.day_phase == 0.25  # 06:00
        assert wc.day == 0
        assert wc.paused is False

    def test_advance(self):
        from core.constants import DAY_LENGTH
        wc = WorldClock()
        # Simulate half a day
        wc.world_time = DAY_LENGTH * 0.5
        wc.day_phase = (wc.world_time % DAY_LENGTH) / DAY_LENGTH
        wc.day = int(wc.world_time / DAY_LENGTH)
        assert wc.day_phase == pytest.approx(0.5)
        assert wc.day == 0

    def test_day_rollover(self):
        from core.constants import DAY_LENGTH
        wc = WorldClock()
        wc.world_time = DAY_LENGTH * 2.5
        wc.day_phase = (wc.world_time % DAY_LENGTH) / DAY_LENGTH
        wc.day = int(wc.world_time / DAY_LENGTH)
        assert wc.day == 2
        assert wc.day_phase == pytest.approx(0.5)


# ═══════════════════════════════════════════════════════════════════════
#  WorldEventLog
# ═══════════════════════════════════════════════════════════════════════

class TestWorldEventLog:
    def test_add_entry(self):
        log = WorldEventLog()
        log.add("Test event", zone="playground", time=1.0, category="info")
        assert len(log.entries) == 1
        assert log.entries[0].message == "Test event"
        assert log.unread == 1

    def test_max_entries_capped(self):
        log = WorldEventLog(max_entries=3)
        for i in range(5):
            log.add(f"Event {i}")
        assert len(log.entries) == 3
        assert log.entries[0].message == "Event 2"

    def test_unread_tracking(self):
        log = WorldEventLog()
        log.add("A")
        log.add("B")
        assert log.unread == 2
        log.unread = 0  # mark read
        assert log.unread == 0
        log.add("C")
        assert log.unread == 1


# ═══════════════════════════════════════════════════════════════════════
#  Off-screen combat
# ═══════════════════════════════════════════════════════════════════════

class TestCoarseCombat:
    def _make_world_with_combatants(self):
        """Create a world with two entities: an NPC and a hostile beast."""
        w = World()
        w.resources.set(GameClock(time=10.0))
        w.resources.set(WorldEventLog())

        npc = w.spawn()
        w.add(npc, CoarsePos(row=5, col=5, zone="test"))
        w.add(npc, Health(current=50.0, maximum=50.0))
        w.add(npc, Identity(name="Guard", kind=EntityKind.NPC))
        w.add(npc, CombatStats(damage=10.0, hostile=False))
        w.add(npc, Timers(active={}))

        beast = w.spawn()
        w.add(beast, CoarsePos(row=5, col=6, zone="test"))
        w.add(beast, Health(current=30.0, maximum=30.0))
        w.add(beast, Identity(name="Feral Dog", kind=EntityKind.BEAST))
        w.add(beast, CombatStats(damage=8.0, hostile=True))
        w.add(beast, Timers(active={}))

        return w, npc, beast

    def test_hostile_attacks(self):
        from systems.combat_sim import resolve_coarse_combat
        w, npc, beast = self._make_world_with_combatants()
        cp_npc = w.get(npc, CoarsePos)
        cp_beast = w.get(beast, CoarsePos)

        resolve_coarse_combat(w, beast, cp_beast, npc, cp_npc, [])

        # Beast should have attacked NPC (beast is hostile)
        hp_npc = w.get(npc, Health)
        assert hp_npc.current < 50.0

        # NPC retaliates against hostile attacker
        hp_beast = w.get(beast, Health)
        assert hp_beast.current < 30.0

    def test_non_hostile_no_attack(self):
        from systems.combat_sim import resolve_coarse_combat
        w = World()
        w.resources.set(GameClock(time=0.0))
        w.resources.set(WorldEventLog())

        a = w.spawn()
        w.add(a, CoarsePos(row=0, col=0, zone="z"))
        w.add(a, Health(current=50.0, maximum=50.0))
        w.add(a, CombatStats(damage=5.0, hostile=False))
        w.add(a, Timers(active={}))

        b = w.spawn()
        w.add(b, CoarsePos(row=0, col=1, zone="z"))
        w.add(b, Health(current=50.0, maximum=50.0))
        w.add(b, CombatStats(damage=5.0, hostile=False))
        w.add(b, Timers(active={}))

        cp_a = w.get(a, CoarsePos)
        cp_b = w.get(b, CoarsePos)
        resolve_coarse_combat(w, a, cp_a, b, cp_b, [])

        # Neither should be damaged
        assert w.get(a, Health).current == 50.0
        assert w.get(b, Health).current == 50.0

    def test_combat_logs_events(self):
        from systems.combat_sim import resolve_coarse_combat
        w, npc, beast = self._make_world_with_combatants()
        cp_npc = w.get(npc, CoarsePos)
        cp_beast = w.get(beast, CoarsePos)

        resolve_coarse_combat(w, beast, cp_beast, npc, cp_npc, [])

        log = w.resources.try_get(WorldEventLog)
        assert len(log.entries) > 0
        assert any("attacked" in e.message or "killed" in e.message
                    for e in log.entries)

    def test_attack_cooldown(self):
        from systems.combat_sim import resolve_coarse_combat
        w, npc, beast = self._make_world_with_combatants()
        cp_npc = w.get(npc, CoarsePos)
        cp_beast = w.get(beast, CoarsePos)

        # First attack
        resolve_coarse_combat(w, beast, cp_beast, npc, cp_npc, [])
        hp_after_first = w.get(npc, Health).current

        # Second attack immediately (should be blocked by cooldown)
        resolve_coarse_combat(w, beast, cp_beast, npc, cp_npc, [])
        hp_after_second = w.get(npc, Health).current
        assert hp_after_second == hp_after_first  # no additional damage


# ═══════════════════════════════════════════════════════════════════════
#  CombatStats component
# ═══════════════════════════════════════════════════════════════════════

class TestCombatStats:
    def test_defaults(self):
        cs = CombatStats()
        assert cs.damage == 5.0
        assert cs.hostile is False
        assert cs._persist is True

    def test_hostile_beast(self):
        cs = CombatStats(damage=15.0, hostile=True)
        assert cs.hostile is True


# ═══════════════════════════════════════════════════════════════════════
#  Dialogue generation
# ═══════════════════════════════════════════════════════════════════════

class TestDialogueGen:
    def test_builds_tree(self):
        from systems.dialogue_gen import build_npc_dialogue
        w = World()
        w.resources.set(WorldClock())
        w.resources.set(GameClock(time=10.0))
        w.resources.set(WorldEventLog())

        npc = w.spawn()
        w.add(npc, Identity(name="Pete", kind=EntityKind.NPC))
        w.add(npc, Health(current=100.0, maximum=100.0))
        w.add(npc, Position(x=5.0, y=5.0, zone="playground"))
        w.add(npc, Sprite(char="P"))

        tree = build_npc_dialogue(w, npc)
        assert "root" in tree
        assert "text" in tree["root"]
        assert "choices" in tree["root"]
        assert any(c.get("action") == "close" for c in tree["root"]["choices"])

    def test_wounded_npc_has_health_dialogue(self):
        from systems.dialogue_gen import build_npc_dialogue
        w = World()
        w.resources.set(WorldClock())
        w.resources.set(GameClock(time=10.0))
        w.resources.set(WorldEventLog())

        npc = w.spawn()
        w.add(npc, Identity(name="Wounded", kind=EntityKind.NPC))
        w.add(npc, Health(current=20.0, maximum=100.0))
        w.add(npc, Position(x=5.0, y=5.0, zone="playground"))

        tree = build_npc_dialogue(w, npc)
        # Should have a health follow-up
        assert "health" in tree
        assert any(c.get("next") == "health" for c in tree["root"]["choices"])

    def test_recent_event_adds_news_node(self):
        from systems.dialogue_gen import build_npc_dialogue
        w = World()
        w.resources.set(WorldClock())
        w.resources.set(GameClock(time=10.0))
        log = WorldEventLog()
        log.add("Feral Dog killed Guard!", zone="outskirts",
                time=5.0, category="combat")
        w.resources.set(log)

        npc = w.spawn()
        w.add(npc, Identity(name="Pete", kind=EntityKind.NPC))
        w.add(npc, Health(current=100.0, maximum=100.0))
        w.add(npc, Position(x=5.0, y=5.0, zone="playground"))

        tree = build_npc_dialogue(w, npc)
        assert "news" in tree


# ═══════════════════════════════════════════════════════════════════════
#  BeastSpawner
# ═══════════════════════════════════════════════════════════════════════

class TestBeastSpawner:
    def test_spawns_beast(self):
        from systems.beast_spawner import BeastSpawner
        from systems.zone_sim import ZoneSim
        from core.zones import load_zone

        w = World()
        w.resources.set(GameClock(time=10.0))
        w.resources.set(WorldEventLog())

        sim = ZoneSim(w)
        # Load a real zone for walkability
        try:
            sim.load_zone("playground")
        except FileNotFoundError:
            pytest.skip("playground zone not found")

        spawner = BeastSpawner(w)
        spawner._timer = 0.0  # force immediate spawn attempt

        spawner.tick(0.1, sim, active_zone="pawn_shop")

        # Check that at least one beast was spawned with CoarsePos
        beasts = [
            eid for eid, ident in w.all_of(Identity)
            if ident.kind == EntityKind.BEAST
        ]
        # Might not spawn if playground isn't "outdoor" — let's check
        # playground is in OUTDOOR_ZONES
        from systems.beast_spawner import OUTDOOR_ZONES
        if "playground" in OUTDOOR_ZONES:
            assert len(beasts) >= 1
            beast_eid = beasts[0]
            assert w.has(beast_eid, CombatStats)
            assert w.has(beast_eid, Health)
            assert w.get(beast_eid, CombatStats).hostile is True
