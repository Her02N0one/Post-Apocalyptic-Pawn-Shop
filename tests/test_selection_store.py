"""Tests for Phase 2 Selection Store & UID infrastructure.

Covers:
1. Zone UID allocation (next_uid monotonic, ensure_uids migration)
2. SelectionStore cell selection (select, add, toggle, rect, line)
3. SelectionStore object selection (select, add, toggle, deselect, primary)
4. UID-based deletion (on_object_deleted — no index fixup)
5. Module helpers (uid_of, resolve_index)
6. Event emission (SelectionChanged on every mutation)
7. Backward-compat shims (objects property)
8. Edge cases (double deselect, delete unselected, empty store queries)
"""

from __future__ import annotations

import sys
import types
import pytest
from dataclasses import dataclass, field
from typing import Any

# ── Bypass editor.view_3d.__init__ (it imports the full editor chain
#    which needs Python 3.10 slots=True and pygame). We only need the
#    selection_store module, so we stub the package entry.
if "editor.view_3d" not in sys.modules:
    _stub = types.ModuleType("editor.view_3d")
    import os as _os
    _stub.__path__ = [_os.path.join(_os.path.dirname(_os.path.dirname(__file__)),
                                     "editor", "view_3d")]
    _stub.__package__ = "editor.view_3d"
    sys.modules["editor.view_3d"] = _stub

from editor.view_3d.selection_store import (
    SelectionStore,
    _get_uid,
    uid_of,
    resolve_index,
    _STORES,
)
from editor.commands.events import SelectionChanged


# ── Minimal Zone stub ─────────────────────────────────────────────

@dataclass
class OverlayWallStub:
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 1.0
    y2: float = 1.0
    uid: int = 0


@dataclass
class ZoneStub:
    """Minimal zone-like object for testing."""
    entities: list[dict[str, Any]] = field(default_factory=list)
    boxes: list[dict[str, Any]] = field(default_factory=list)
    quads: list[dict[str, Any]] = field(default_factory=list)
    render_portals: list[dict[str, Any]] = field(default_factory=list)
    curves: list[dict[str, Any]] = field(default_factory=list)
    overlay_walls: list[Any] = field(default_factory=list)
    _next_uid: int = 1

    def next_uid(self) -> int:
        uid = self._next_uid
        self._next_uid = uid + 1
        return uid


# ── Fake EventBus ─────────────────────────────────────────────────

class FakeEventBus:
    """Records all emitted events for assertion."""
    def __init__(self):
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)

    def subscribe(self, *args, **kwargs):
        pass

    @property
    def last(self) -> Any:
        return self.events[-1] if self.events else None

    def clear(self):
        self.events.clear()


# ══════════════════════════════════════════════════════════════════
#  1. Zone UID allocation
# ══════════════════════════════════════════════════════════════════

class TestZoneUID:
    def test_next_uid_monotonic(self):
        z = ZoneStub()
        ids = [z.next_uid() for _ in range(5)]
        assert ids == [1, 2, 3, 4, 5]
        assert z._next_uid == 6

    def test_next_uid_starts_from_custom_value(self):
        z = ZoneStub(_next_uid=100)
        assert z.next_uid() == 100
        assert z.next_uid() == 101


class TestZoneEnsureUIDs:
    """Test ensure_uids via the real Zone class."""

    def test_ensure_uids_assigns_missing(self):
        from core.zones.zone import Zone, OverlayWall
        z = Zone(
            name="test", width=2, height=2,
            anchor=(0.0, 0.0),
            tiles=[["floor"] * 2 for _ in range(2)],
            entities=[{"id": "goblin", "x": 0, "y": 0}],
            boxes=[{"x": 1, "y": 1, "uid": 0}],
            overlay_walls=[OverlayWall(0, 0, 1, 1)],
        )
        z.ensure_uids()
        assert z.entities[0]["uid"] > 0
        assert z.boxes[0]["uid"] > 0
        assert z.overlay_walls[0].uid > 0
        # All UIDs are distinct
        uids = {z.entities[0]["uid"], z.boxes[0]["uid"], z.overlay_walls[0].uid}
        assert len(uids) == 3

    def test_ensure_uids_idempotent(self):
        from core.zones.zone import Zone
        z = Zone(
            name="test", width=1, height=1,
            anchor=(0.0, 0.0),
            tiles=[["floor"]],
            entities=[{"id": "a", "x": 0, "y": 0, "uid": 42}],
        )
        z.ensure_uids()
        assert z.entities[0]["uid"] == 42  # kept existing UID


# ══════════════════════════════════════════════════════════════════
#  2. Module helpers
# ══════════════════════════════════════════════════════════════════

class TestGetUID:
    def test_dict_with_uid(self):
        assert _get_uid({"uid": 7, "x": 1}) == 7

    def test_dict_missing_uid(self):
        assert _get_uid({"x": 1}) == 0

    def test_dataclass_with_uid(self):
        ow = OverlayWallStub(uid=42)
        assert _get_uid(ow) == 42

    def test_dataclass_no_uid(self):
        @dataclass
        class NakedObj:
            x: int = 0
        assert _get_uid(NakedObj()) == 0


class TestUidOf:
    def test_valid_entity(self):
        z = ZoneStub(entities=[{"uid": 10, "x": 0}, {"uid": 20, "x": 1}])
        assert uid_of(z, "entity", 0) == 10
        assert uid_of(z, "entity", 1) == 20

    def test_valid_overlay(self):
        z = ZoneStub(overlay_walls=[OverlayWallStub(uid=55)])
        assert uid_of(z, "overlay", 0) == 55

    def test_out_of_bounds(self):
        z = ZoneStub(entities=[{"uid": 1}])
        assert uid_of(z, "entity", 5) is None
        assert uid_of(z, "entity", -1) is None

    def test_unknown_type_tag(self):
        z = ZoneStub()
        assert uid_of(z, "unknown", 0) is None

    def test_zero_uid_returns_none(self):
        z = ZoneStub(entities=[{"x": 1}])  # no uid key → _get_uid returns 0
        assert uid_of(z, "entity", 0) is None


class TestResolveIndex:
    def test_found(self):
        z = ZoneStub(boxes=[{"uid": 5}, {"uid": 10}, {"uid": 15}])
        assert resolve_index(z, "prism", 10) == 1

    def test_not_found(self):
        z = ZoneStub(boxes=[{"uid": 5}])
        assert resolve_index(z, "prism", 999) is None

    def test_overlay(self):
        z = ZoneStub(overlay_walls=[
            OverlayWallStub(uid=1),
            OverlayWallStub(uid=2),
        ])
        assert resolve_index(z, "overlay", 2) == 1

    def test_empty_store(self):
        z = ZoneStub()
        assert resolve_index(z, "entity", 1) is None

    def test_unknown_type(self):
        z = ZoneStub()
        assert resolve_index(z, "banana", 1) is None


class TestStoresMapping:
    def test_all_six_types(self):
        assert set(_STORES.keys()) == {
            "entity", "prism", "quad", "portal", "curve", "overlay",
        }


# ══════════════════════════════════════════════════════════════════
#  3. Cell selection
# ══════════════════════════════════════════════════════════════════

class TestCellSelection:
    def test_select_cell(self):
        s = SelectionStore()
        s.select_cell(3, 4)
        assert s.cells == {(3, 4)}
        s.select_cell(5, 6)
        assert s.cells == {(5, 6)}  # replaces

    def test_add_cell(self):
        s = SelectionStore()
        s.add_cell(0, 0)
        s.add_cell(1, 1)
        assert s.cells == {(0, 0), (1, 1)}

    def test_toggle_cell(self):
        s = SelectionStore()
        s.toggle_cell(2, 2)
        assert (2, 2) in s.cells
        s.toggle_cell(2, 2)
        assert (2, 2) not in s.cells

    def test_select_rect(self):
        s = SelectionStore()
        s.select_rect(0, 0, 2, 2)
        assert s.cells == {
            (0, 0), (0, 1), (0, 2),
            (1, 0), (1, 1), (1, 2),
            (2, 0), (2, 1), (2, 2),
        }

    def test_add_rect_extends(self):
        s = SelectionStore()
        s.select_cell(5, 5)
        s.add_rect(0, 0, 1, 1)
        assert (5, 5) in s.cells
        assert (0, 0) in s.cells

    def test_add_line_horizontal(self):
        s = SelectionStore()
        s.add_line(0, 0, 0, 3)
        assert s.cells == {(0, 0), (0, 1), (0, 2), (0, 3)}

    def test_select_all_cells(self):
        s = SelectionStore()
        s.select_all_cells(3, 2)
        assert len(s.cells) == 6  # 2 rows × 3 cols

    def test_clear_cells(self):
        s = SelectionStore()
        s.select_rect(0, 0, 5, 5)
        s.clear_cells()
        assert not s.has_cells()
        assert s.anchor is None

    def test_bounds(self):
        s = SelectionStore()
        s.add_cell(1, 3)
        s.add_cell(4, 0)
        assert s.bounds() == (1, 0, 4, 3)

    def test_bounds_empty(self):
        s = SelectionStore()
        assert s.bounds() is None

    def test_contains_cell(self):
        s = SelectionStore()
        s.add_cell(2, 3)
        assert s.contains_cell(2, 3)
        assert not s.contains_cell(0, 0)


class TestRectDrag:
    def test_begin_finish(self):
        s = SelectionStore()
        s.begin_rect(0, 0)
        assert s.rect_in_progress
        s.update_rect(2, 2)
        preview = s.rect_preview
        assert preview == (0, 0, 2, 2)
        s.finish_rect(2, 2)
        assert not s.rect_in_progress
        assert len(s.cells) == 9  # 3×3

    def test_finish_extend(self):
        s = SelectionStore()
        s.select_cell(5, 5)
        s.begin_rect(0, 0)
        s.finish_rect(1, 1, extend=True)
        assert (5, 5) in s.cells  # original preserved
        assert (0, 0) in s.cells

    def test_cancel_rect(self):
        s = SelectionStore()
        s.begin_rect(0, 0)
        s.cancel_rect()
        assert not s.rect_in_progress
        assert s.rect_preview is None

    def test_preview_none_without_end(self):
        s = SelectionStore()
        s.begin_rect(1, 1)
        assert s.rect_preview is None  # no update_rect yet


# ══════════════════════════════════════════════════════════════════
#  4. Object selection (UID-based)
# ══════════════════════════════════════════════════════════════════

class TestObjectSelection:
    def test_select_object(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        assert s.has_objects()
        assert s.object_count() == 1
        assert s.primary_uid == 10
        assert s.primary_type == "entity"
        assert s.is_object_selected(10)

    def test_select_object_replaces_prior(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.select_object("prism", 20)
        assert s.object_count() == 1
        assert not s.is_object_selected(10)
        assert s.is_object_selected(20)
        assert s.primary_uid == 20

    def test_add_object_multi_select(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.add_object("entity", 20)
        s.add_object("prism", 30)
        assert s.object_count() == 3
        assert s.primary_uid == 10  # first stays primary

    def test_toggle_object_on_off(self):
        s = SelectionStore()
        s.toggle_object("quad", 5)
        assert s.is_object_selected(5)
        assert s.primary_uid == 5
        s.toggle_object("quad", 5)
        assert not s.is_object_selected(5)
        assert s.primary_uid is None

    def test_toggle_object_primary_transfers(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.add_object("entity", 20)
        s.toggle_object("entity", 10)  # deselect primary
        assert s.primary_uid == 20  # transfers to remaining

    def test_deselect_object(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.deselect_object(10)
        assert not s.has_objects()
        assert s.primary_uid is None

    def test_deselect_object_not_selected_is_noop(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.deselect_object(999)  # not selected
        assert len(bus.events) == 0  # no event

    def test_clear_objects(self):
        s = SelectionStore()
        s.select_object("entity", 1)
        s.add_object("prism", 2)
        s.clear_objects()
        assert not s.has_objects()
        assert s.primary_uid is None

    def test_clear_objects_empty_is_noop(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.clear_objects()
        assert len(bus.events) == 0  # no event when nothing to clear

    def test_primary_index(self):
        z = ZoneStub(entities=[
            {"uid": 10, "x": 0},
            {"uid": 20, "x": 1},
            {"uid": 30, "x": 2},
        ])
        s = SelectionStore()
        s.select_object("entity", 20)
        assert s.primary_index(z) == 1

    def test_primary_index_none(self):
        z = ZoneStub()
        s = SelectionStore()
        assert s.primary_index(z) is None

    def test_selected_uids_by_type(self):
        s = SelectionStore()
        s.select_object("entity", 1)
        s.add_object("entity", 2)
        s.add_object("prism", 3)
        assert set(s.selected_uids_by_type("entity")) == {1, 2}
        assert s.selected_uids_by_type("prism") == [3]
        assert s.selected_uids_by_type("quad") == []

    def test_iter_objects(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.add_object("prism", 20)
        result = set(s.iter_objects())
        assert result == {("entity", 10), ("prism", 20)}

    def test_contains_object(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        assert s.contains_object("entity", 10)
        assert not s.contains_object("prism", 10)  # wrong type
        assert not s.contains_object("entity", 99)  # wrong uid


# ══════════════════════════════════════════════════════════════════
#  5. UID-based deletion
# ══════════════════════════════════════════════════════════════════

class TestObjectDeletion:
    def test_on_object_deleted_removes_from_selection(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.add_object("entity", 20)
        s.on_object_deleted(10)
        assert not s.is_object_selected(10)
        assert s.is_object_selected(20)
        assert s.primary_uid == 20  # transferred

    def test_on_object_deleted_unselected_is_noop(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        bus.clear()
        s.on_object_deleted(999)
        assert len(bus.events) == 0  # no event

    def test_on_object_deleted_last_clears_primary(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.on_object_deleted(10)
        assert s.primary_uid is None
        assert not s.has_objects()

    def test_on_object_inserted_is_noop(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.on_object_inserted("entity", 42)
        assert len(bus.events) == 0

    def test_no_index_fixup_needed(self):
        """After deleting object at index 0, object at index 1's UID
        is still valid — no index adjustment needed."""
        z = ZoneStub(entities=[
            {"uid": 10, "x": 0},
            {"uid": 20, "x": 1},
            {"uid": 30, "x": 2},
        ])
        s = SelectionStore()
        s.select_object("entity", 30)

        # Delete entity at index 0 (uid=10)
        z.entities.pop(0)
        s.on_object_deleted(10)

        # uid=30 is still selected, and resolves to index 1 (shifted)
        assert s.is_object_selected(30)
        assert s.primary_uid == 30
        assert resolve_index(z, "entity", 30) == 1  # was 2, now 1


# ══════════════════════════════════════════════════════════════════
#  6. Event emission
# ══════════════════════════════════════════════════════════════════

class TestEventEmission:
    def test_select_object_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        assert len(bus.events) == 1
        evt = bus.events[0]
        assert isinstance(evt, SelectionChanged)
        assert ("entity", 10) in evt.objects

    def test_add_object_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 1)
        bus.clear()
        s.add_object("prism", 2)
        assert len(bus.events) == 1

    def test_toggle_object_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.toggle_object("quad", 5)
        assert len(bus.events) == 1

    def test_deselect_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        bus.clear()
        s.deselect_object(10)
        assert len(bus.events) == 1

    def test_on_object_deleted_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        bus.clear()
        s.on_object_deleted(10)
        assert len(bus.events) == 1

    def test_clear_objects_emits(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.select_object("entity", 10)
        bus.clear()
        s.clear_objects()
        assert len(bus.events) == 1

    def test_no_bus_no_crash(self):
        """SelectionStore works without an event bus."""
        s = SelectionStore()  # no bus
        s.select_object("entity", 1)
        s.on_object_deleted(1)
        s.clear_objects()
        # No exceptions

    def test_event_contains_cells_and_objects(self):
        bus = FakeEventBus()
        s = SelectionStore(bus)
        s.add_cell(2, 3)
        s.select_object("entity", 10)
        evt = bus.last
        assert isinstance(evt, SelectionChanged)
        assert (2, 3) in evt.cells
        assert ("entity", 10) in evt.objects


# ══════════════════════════════════════════════════════════════════
#  7. Backward-compat shims
# ══════════════════════════════════════════════════════════════════

class TestBackwardCompat:
    def test_objects_property(self):
        s = SelectionStore()
        s.select_object("entity", 10)
        s.add_object("prism", 20)
        assert s.objects == {("entity", 10), ("prism", 20)}

    def test_objects_property_empty(self):
        s = SelectionStore()
        assert s.objects == set()


# ══════════════════════════════════════════════════════════════════
#  8. Combined / edge cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_has_anything(self):
        s = SelectionStore()
        assert not s.has_anything()
        s.add_cell(0, 0)
        assert s.has_anything()
        s.clear_cells()
        s.select_object("entity", 1)
        assert s.has_anything()

    def test_clear_both(self):
        s = SelectionStore()
        s.add_cell(1, 1)
        s.select_object("entity", 5)
        s.clear()
        assert not s.has_anything()

    def test_cell_count_and_object_count(self):
        s = SelectionStore()
        assert s.cell_count() == 0
        assert s.object_count() == 0
        s.add_cell(1, 1)
        s.add_cell(2, 2)
        s.select_object("entity", 1)
        assert s.cell_count() == 2
        assert s.object_count() == 1

    def test_iter_cells(self):
        s = SelectionStore()
        s.add_cell(0, 0)
        s.add_cell(1, 1)
        assert set(s.iter_cells()) == {(0, 0), (1, 1)}

    def test_ceiling_mode_toggle(self):
        s = SelectionStore()
        assert not s.ceiling_mode
        s.toggle_ceiling_mode()
        assert s.ceiling_mode
        s.toggle_ceiling_mode()
        assert not s.ceiling_mode

    def test_select_objects_in_rect(self):
        z = ZoneStub(
            entities=[
                {"uid": 1, "x": 1.5, "y": 2.5},  # col=1, row=2 → in rect
                {"uid": 2, "x": 5.0, "y": 5.0},  # col=5, row=5 → out
            ],
            boxes=[
                {"uid": 3, "x": 0.5, "y": 0.5},  # col=0, row=0 → in rect
            ],
        )
        s = SelectionStore()
        s.select_objects_in_rect(0, 0, 3, 3, z)
        assert s.is_object_selected(1)
        assert not s.is_object_selected(2)
        assert s.is_object_selected(3)
        assert s.object_count() == 2

    def test_select_objects_in_rect_overlays(self):
        z = ZoneStub(
            overlay_walls=[
                OverlayWallStub(x1=0, y1=0, x2=2, y2=2, uid=10),  # midpoint (1,1)
                OverlayWallStub(x1=8, y1=8, x2=10, y2=10, uid=20),  # midpoint (9,9)
            ],
        )
        s = SelectionStore()
        s.select_objects_in_rect(0, 0, 3, 3, z)
        assert s.is_object_selected(10)
        assert not s.is_object_selected(20)
