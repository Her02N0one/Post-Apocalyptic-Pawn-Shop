"""tests/test_lod.py — Tests for dual-resolution LOD system.

Covers:
- CoarsePos / Timers / WorldClock component basics
- Promote/demote logic (CoarsePos ↔ Position)
- sync_zone_lod bulk transition
- Timer ticking + expiry
- ZoneSim coarse movement
- ZoneSim portal traversal
- ZoneSim sight checks (tile LOS)
"""

import pytest
from core.ecs import World
from components import (
    Position, Velocity, Sprite, Identity, Facing, Collider,
    Health, CoarsePos, Timers, Player, Camera, WorldClock,
)
from core.types import EntityKind
from systems.lod import promote, demote, sync_zone_lod, tick_timers
from systems.zone_sim import ZoneSim, ZoneCache, _tile_los, _step_toward


# ═══════════════════════════════════════════════════════════════════
#  Component basics
# ═══════════════════════════════════════════════════════════════════

class TestCoarsePos:
    def test_persists(self):
        assert CoarsePos._persist is True

    def test_defaults(self):
        cp = CoarsePos()
        assert cp.row == 0
        assert cp.col == 0
        assert cp.zone == "playground"
        assert cp.speed == 2.0

    def test_custom_values(self):
        cp = CoarsePos(row=5, col=10, zone="ruins", speed=3.5)
        assert cp.row == 5
        assert cp.col == 10
        assert cp.zone == "ruins"
        assert cp.speed == 3.5


class TestTimers:
    def test_persists(self):
        assert Timers._persist is True

    def test_empty_by_default(self):
        t = Timers()
        assert t.active == {}

    def test_set_and_check(self):
        t = Timers(active={"attack_cd": 0.5})
        assert "attack_cd" in t.active
        assert t.active["attack_cd"] == 0.5


class TestWorldClock:
    def test_defaults(self):
        wc = WorldClock()
        assert wc.real_time == 0.0
        assert wc.world_time == 0.0
        assert wc.day == 0
        assert wc.day_phase == 0.25  # 06:00
        assert wc.paused is False


# ═══════════════════════════════════════════════════════════════════
#  Promote / Demote
# ═══════════════════════════════════════════════════════════════════

class TestPromote:
    def test_creates_position_from_coarse(self):
        w = World()
        e = w.spawn()
        w.add(e, CoarsePos(row=5, col=10, zone="test"))
        promote(w, e)
        pos = w.get(e, Position)
        assert pos is not None
        assert pos.x == 10.5
        assert pos.y == 5.5
        assert pos.zone == "test"

    def test_adds_velocity(self):
        w = World()
        e = w.spawn()
        w.add(e, CoarsePos(row=3, col=7, zone="test"))
        promote(w, e)
        vel = w.get(e, Velocity)
        assert vel is not None
        assert vel.x == 0.0
        assert vel.y == 0.0

    def test_updates_existing_position(self):
        w = World()
        e = w.spawn()
        w.add(e, CoarsePos(row=5, col=10, zone="zone_b"))
        w.add(e, Position(x=0.0, y=0.0, zone="zone_a"))
        promote(w, e)
        pos = w.get(e, Position)
        assert pos.x == 10.5
        assert pos.y == 5.5
        assert pos.zone == "zone_b"

    def test_noop_without_coarse(self):
        w = World()
        e = w.spawn()
        promote(w, e)  # no crash
        assert w.get(e, Position) is None

    def test_keeps_coarse_pos(self):
        w = World()
        e = w.spawn()
        w.add(e, CoarsePos(row=2, col=4, zone="t"))
        promote(w, e)
        assert w.has(e, CoarsePos)


class TestDemote:
    def test_snaps_position_to_coarse(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=7.8, y=3.2, zone="test"))
        w.add(e, Velocity(x=1.0, y=2.0))
        demote(w, e)
        cp = w.get(e, CoarsePos)
        assert cp is not None
        assert cp.col == 7
        assert cp.row == 3
        assert cp.zone == "test"

    def test_removes_position_and_velocity(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=5.5, y=5.5, zone="test"))
        w.add(e, Velocity())
        demote(w, e)
        assert not w.has(e, Position)
        assert not w.has(e, Velocity)

    def test_creates_coarsepos_if_missing(self):
        w = World()
        e = w.spawn()
        w.add(e, Position(x=12.9, y=8.1, zone="ruins"))
        demote(w, e)
        cp = w.get(e, CoarsePos)
        assert cp is not None
        assert cp.row == 8
        assert cp.col == 12

    def test_updates_existing_coarsepos(self):
        w = World()
        e = w.spawn()
        w.add(e, CoarsePos(row=0, col=0, zone="old"))
        w.add(e, Position(x=15.3, y=9.7, zone="new"))
        demote(w, e)
        cp = w.get(e, CoarsePos)
        assert cp.row == 9
        assert cp.col == 15
        assert cp.zone == "new"

    def test_noop_without_position(self):
        w = World()
        e = w.spawn()
        demote(w, e)  # no crash
        assert w.get(e, CoarsePos) is None


class TestSyncZoneLod:
    def _make_world(self):
        w = World()
        # Player in zone_a
        p = w.spawn()
        w.add(p, Player())
        w.add(p, Position(x=5.5, y=5.5, zone="zone_a"))

        # NPC with CoarsePos in zone_a (should get promoted)
        n1 = w.spawn()
        w.add(n1, CoarsePos(row=3, col=7, zone="zone_a"))
        w.add(n1, Identity(name="NPC_A"))

        # NPC with Position in zone_b (should get demoted)
        n2 = w.spawn()
        w.add(n2, Position(x=2.5, y=2.5, zone="zone_b"))
        w.add(n2, CoarsePos(row=2, col=2, zone="zone_b"))
        w.add(n2, Identity(name="NPC_B"))
        w.add(n2, Velocity())

        return w, p, n1, n2

    def test_promotes_active_zone_entities(self):
        w, p, n1, n2 = self._make_world()
        sync_zone_lod(w, "zone_a")
        # n1 should now have Position
        pos = w.get(n1, Position)
        assert pos is not None
        assert pos.x == 7.5
        assert pos.y == 3.5

    def test_demotes_inactive_zone_entities(self):
        w, p, n1, n2 = self._make_world()
        sync_zone_lod(w, "zone_a")
        # n2 should have lost Position
        assert not w.has(n2, Position)
        assert not w.has(n2, Velocity)
        # CoarsePos should be updated
        cp = w.get(n2, CoarsePos)
        assert cp is not None

    def test_player_never_demoted(self):
        w, p, n1, n2 = self._make_world()
        # Player is in zone_a, switch active to zone_b
        sync_zone_lod(w, "zone_b")
        # Player should still have Position
        assert w.has(p, Position)


# ═══════════════════════════════════════════════════════════════════
#  Timer ticking
# ═══════════════════════════════════════════════════════════════════

class TestTickTimers:
    def test_decrements(self):
        w = World()
        e = w.spawn()
        w.add(e, Timers(active={"cd": 1.0}))
        tick_timers(w, 0.3)
        t = w.get(e, Timers)
        assert abs(t.active["cd"] - 0.7) < 0.001

    def test_removes_expired(self):
        w = World()
        e = w.spawn()
        w.add(e, Timers(active={"cd": 0.1}))
        tick_timers(w, 0.5)
        t = w.get(e, Timers)
        assert "cd" not in t.active

    def test_multiple_timers(self):
        w = World()
        e = w.spawn()
        w.add(e, Timers(active={"a": 1.0, "b": 0.2, "c": 0.5}))
        tick_timers(w, 0.3)
        t = w.get(e, Timers)
        assert "a" in t.active  # 0.7 remaining
        assert "b" not in t.active  # expired
        assert "c" in t.active  # 0.2 remaining

    def test_no_timers_noop(self):
        w = World()
        e = w.spawn()
        w.add(e, Timers(active={}))
        tick_timers(w, 10.0)  # no crash


# ═══════════════════════════════════════════════════════════════════
#  Tile LOS
# ═══════════════════════════════════════════════════════════════════

class TestTileLOS:
    def _open_grid(self, h: int = 10, w: int = 10):
        """Create a fully open tile grid (all walkable, tile id 1)."""
        return [[1] * w for _ in range(h)]

    def test_clear_line(self):
        tiles = self._open_grid()
        assert _tile_los(tiles, 0, 0, 5, 5) is True

    def test_blocked_by_wall(self):
        tiles = self._open_grid()
        from core.tiles import SOLID_IDS
        # Get any solid tile id
        solid_id = next(iter(SOLID_IDS))
        tiles[3][3] = solid_id
        # Line from (0,0) to (5,5) passes through (3,3)
        assert _tile_los(tiles, 0, 0, 5, 5) is False

    def test_same_tile(self):
        tiles = self._open_grid()
        assert _tile_los(tiles, 4, 4, 4, 4) is True

    def test_out_of_range(self):
        tiles = self._open_grid(50, 50)
        assert _tile_los(tiles, 0, 0, 40, 40, max_range=10) is False

    def test_adjacent(self):
        tiles = self._open_grid()
        assert _tile_los(tiles, 5, 5, 5, 6) is True
        assert _tile_los(tiles, 5, 5, 6, 5) is True


# ═══════════════════════════════════════════════════════════════════
#  Step toward
# ═══════════════════════════════════════════════════════════════════

class TestStepToward:
    def test_move_right(self):
        assert _step_toward(5, 5, 5, 8) == (5, 6)

    def test_move_left(self):
        assert _step_toward(5, 5, 5, 2) == (5, 4)

    def test_move_down(self):
        assert _step_toward(5, 5, 8, 5) == (6, 5)

    def test_move_up(self):
        assert _step_toward(5, 5, 2, 5) == (4, 5)

    def test_diagonal_prefers_larger_axis(self):
        # dr=3, dc=1 → move row first
        assert _step_toward(5, 5, 8, 6) == (6, 5)

    def test_already_there(self):
        assert _step_toward(5, 5, 5, 5) == (5, 5)


# ═══════════════════════════════════════════════════════════════════
#  ZoneSim
# ═══════════════════════════════════════════════════════════════════

class TestZoneSim:
    def _make_sim(self) -> tuple[World, ZoneSim]:
        w = World()
        sim = ZoneSim(w, tick_interval=1.0)
        # Create a simple 10x10 zone with walkable interior
        from core.tiles import SOLID_IDS
        solid_id = next(iter(SOLID_IDS))
        tiles: list[list[int]] = []
        for r in range(10):
            row = []
            for c in range(10):
                if r == 0 or r == 9 or c == 0 or c == 9:
                    row.append(solid_id)  # border walls
                else:
                    row.append(1)  # walkable
            tiles.append(row)

        from core.zones import Zone, Portal
        zone = Zone(
            name="test_zone",
            width=10, height=10,
            anchor=(5.0, 5.0),
            tiles=tiles,
            portals=[],
            entities=[],
        )
        sim.load_zone("test_zone", zone)
        return w, sim

    def test_load_zone(self):
        w, sim = self._make_sim()
        assert sim.has_zone("test_zone")
        zc = sim.get_zone("test_zone")
        assert zc is not None
        assert zc.height == 10
        assert zc.width == 10

    def test_tick_accumulation(self):
        w, sim = self._make_sim()
        # 0.5s — not enough for a tick
        ticks = sim.tick(0.5, active_zone="other")
        assert ticks == 0
        # Another 0.6s — now past 1.0s threshold
        ticks = sim.tick(0.6, active_zone="other")
        assert ticks == 1

    def test_skips_active_zone(self):
        w, sim = self._make_sim()
        # Spawn coarse NPC in test_zone
        e = w.spawn()
        w.add(e, CoarsePos(row=5, col=5, zone="test_zone", speed=2.0))
        w.add(e, Identity(name="NPC"))
        w.add(e, Timers(active={}))

        old_r, old_c = 5, 5
        # Tick with test_zone as active — should NOT move
        sim.tick(2.0, active_zone="test_zone")
        cp = w.get(e, CoarsePos)
        # Can't guarantee no movement but the zone was supposed to be skipped
        # Actually with active_zone == test_zone, the zone sim skips it
        assert cp.row == old_r and cp.col == old_c

    def test_coarse_entity_moves(self):
        w, sim = self._make_sim()
        e = w.spawn()
        w.add(e, CoarsePos(row=5, col=5, zone="test_zone", speed=2.0))
        w.add(e, Identity(name="Mover"))
        w.add(e, Timers(active={}))

        # Tick until the NPC has a chance to move
        moved = False
        for _ in range(20):  # up to 20 ticks
            sim.tick(1.0, active_zone="other")
            tick_timers(w, 1.0)  # clear move cooldowns
            cp = w.get(e, CoarsePos)
            if cp.row != 5 or cp.col != 5:
                moved = True
                break
        assert moved, "NPC should have moved after multiple ticks"

    def test_entity_with_position_skipped(self):
        """Entities that have fine Position (in active zone) are not moved."""
        w, sim = self._make_sim()
        e = w.spawn()
        w.add(e, CoarsePos(row=5, col=5, zone="test_zone"))
        w.add(e, Position(x=5.5, y=5.5, zone="test_zone"))  # promoted
        w.add(e, Timers(active={}))

        sim.tick(5.0, active_zone="other")
        cp = w.get(e, CoarsePos)
        # Should not have been touched by the sim
        assert cp.row == 5 and cp.col == 5

    def test_zone_entity_positions(self):
        w, sim = self._make_sim()
        e = w.spawn()
        w.add(e, CoarsePos(row=3, col=7, zone="test_zone"))
        w.add(e, Identity(name="Test"))

        positions = sim.zone_entity_positions("test_zone")
        assert len(positions) == 1
        eid, row, col, name = positions[0]
        assert eid == e
        assert row == 3
        assert col == 7
        assert name == "Test"


class TestZoneSimPortal:
    def _make_linked_zones(self) -> tuple[World, ZoneSim]:
        """Create two zones linked by portals."""
        w = World()
        sim = ZoneSim(w, tick_interval=1.0)

        from core.tiles import SOLID_IDS
        solid_id = next(iter(SOLID_IDS))

        def make_zone(name: str) -> list[list[int]]:
            tiles = []
            for r in range(8):
                row = []
                for c in range(8):
                    if r == 0 or r == 7 or c == 0 or c == 7:
                        row.append(solid_id)
                    else:
                        row.append(1)
                tiles.append(row)
            return tiles

        from core.zones import Zone, Portal

        zone_a = Zone(
            name="zone_a", width=8, height=8,
            anchor=(4.0, 4.0),
            tiles=make_zone("zone_a"),
            portals=[Portal(
                tiles=[(3, 7)],  # wall tile but we'll make it walkable for test
                target_zone="zone_b",
                target_row=3, target_col=1,
                exit_direction="right",
            )],
        )
        # Make portal tile walkable
        zone_a.tiles[3][7] = 1

        zone_b = Zone(
            name="zone_b", width=8, height=8,
            anchor=(4.0, 4.0),
            tiles=make_zone("zone_b"),
            portals=[Portal(
                tiles=[(3, 0)],
                target_zone="zone_a",
                target_row=3, target_col=6,
                exit_direction="left",
            )],
        )
        zone_b.tiles[3][0] = 1

        sim.load_zone("zone_a", zone_a)
        sim.load_zone("zone_b", zone_b)

        return w, sim

    def test_portal_teleport(self):
        w, sim = self._make_linked_zones()
        e = w.spawn()
        # Place NPC on the portal tile in zone_a
        w.add(e, CoarsePos(row=3, col=7, zone="zone_a"))
        w.add(e, Identity(name="Traveler"))
        w.add(e, Timers(active={}))

        # Tick — NPC should teleport to zone_b
        sim.tick(1.0, active_zone="neither")
        cp = w.get(e, CoarsePos)
        assert cp.zone == "zone_b"
        assert cp.row == 3
        assert cp.col == 1


# ═══════════════════════════════════════════════════════════════════
#  Save/load round-trip for new components
# ═══════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_coarsepos_round_trip(self):
        from core.save import save_game, load_game, restore_entity
        import tempfile, os

        w = World()
        e = w.spawn()
        w.add(e, Position(x=5.0, y=5.0, zone="test"))
        w.add(e, CoarsePos(row=5, col=5, zone="test", speed=3.0))

        # Save with a temp slot
        slot = 999
        save_game(w, "test", slot=slot)
        try:
            data = load_game(slot)
            assert data is not None
            w2 = World()
            for ent in data["entities"]:
                restore_entity(w2, ent)
            found = False
            for eid, cp in w2.all_of(CoarsePos):
                assert cp.row == 5
                assert cp.col == 5
                assert cp.zone == "test"
                assert cp.speed == 3.0
                found = True
            assert found
        finally:
            from core.save import SAVES_DIR
            p = SAVES_DIR / f"slot_{slot}.json"
            if p.exists():
                p.unlink()

    def test_timers_round_trip(self):
        from core.save import save_game, load_game, restore_entity

        w = World()
        e = w.spawn()
        w.add(e, Position(x=1.0, y=1.0, zone="test"))
        w.add(e, Timers(active={"cd": 0.5, "buff": 3.0}))

        slot = 998
        save_game(w, "test", slot=slot)
        try:
            data = load_game(slot)
            assert data is not None
            w2 = World()
            for ent in data["entities"]:
                restore_entity(w2, ent)
            found = False
            for eid, t in w2.all_of(Timers):
                assert t.active["cd"] == 0.5
                assert t.active["buff"] == 3.0
                found = True
            assert found
        finally:
            from core.save import SAVES_DIR
            p = SAVES_DIR / f"slot_{slot}.json"
            if p.exists():
                p.unlink()
