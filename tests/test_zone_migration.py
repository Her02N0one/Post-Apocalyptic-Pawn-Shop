"""tests/test_zone_migration.py — Verify entity migration script."""

import math
import pytest
from scripts.migrate_zone_entities import (
    migrate_entity,
    PREFAB_TO_TYPE,
    DIRECTION_TO_ANGLE,
)


class TestMigrateEntity:
    """Unit tests for single-entity migration."""

    def test_already_migrated_no_change(self):
        """Entity with 'type' and no 'prefab' is untouched."""
        ent = {
            "id": "barrel_abc",
            "uid": 7,
            "type": "barrel",
            "x": 5.0,
            "y": 3.0,
            "angle": 0.0,
            "state": "default",
            "overrides": {},
        }
        result, changed = migrate_entity(ent)
        assert not changed
        assert result is ent  # same object, not copied

    def test_properties_renamed_to_overrides(self):
        """Entity with 'type' + 'properties' gets renamed."""
        ent = {
            "id": "lamp_1",
            "type": "street_lamp",
            "x": 1.0,
            "y": 2.0,
            "properties": {"health": {"current": 50}},
        }
        result, changed = migrate_entity(ent)
        assert changed
        assert "overrides" in result
        assert "properties" not in result
        assert result["overrides"] == {"health": {"current": 50}}

    def test_legacy_prefab_converted(self):
        """Legacy 'prefab' entity gets full conversion."""
        ent = {
            "id": "shopkeeper",
            "prefab": "merchant",
            "position": {"x": 6.5, "y": 2.5},
            "facing": {"direction": "down"},
        }
        result, changed = migrate_entity(ent)
        assert changed
        assert result["type"] == "merchant_npc"
        assert "prefab" not in result
        assert result["x"] == 6.5
        assert result["y"] == 2.5
        assert "position" not in result
        # facing → angle
        assert result["angle"] == DIRECTION_TO_ANGLE["down"]
        # facing should NOT be in overrides (converted to angle)
        assert "facing" not in result.get("overrides", {})

    def test_inline_overrides_collected(self):
        """Inline component dicts move to 'overrides'."""
        ent = {
            "id": "camp_npc",
            "prefab": "npc",
            "position": {"x": 8.5, "y": 6.5},
            "identity": {"name": "Camper", "kind": "npc"},
            "sprite": {"char": "C", "color": [255, 180, 80], "layer": 5},
        }
        result, changed = migrate_entity(ent)
        assert changed
        assert result["type"] == "survivor_npc"
        ov = result["overrides"]
        assert ov["identity"] == {"name": "Camper", "kind": "npc"}
        assert ov["sprite"] == {"char": "C", "color": [255, 180, 80], "layer": 5}

    def test_crate_maps_to_wooden_crate(self):
        """Prefab 'crate' maps to type 'wooden_crate'."""
        ent = {
            "id": "crate_1",
            "prefab": "crate",
            "position": {"x": 1.0, "y": 2.0},
        }
        result, _ = migrate_entity(ent)
        assert result["type"] == "wooden_crate"

    def test_missing_position_defaults_to_zero(self):
        """Entity with no position gets (0, 0)."""
        ent = {"id": "orphan", "prefab": "dummy"}
        result, _ = migrate_entity(ent)
        assert result["x"] == 0.0
        assert result["y"] == 0.0

    def test_unknown_prefab_kept_as_is(self):
        """Unknown prefab name passes through unchanged."""
        ent = {
            "id": "alien",
            "prefab": "alien_visitor",
            "position": {"x": 1.0, "y": 1.0},
        }
        result, _ = migrate_entity(ent)
        assert result["type"] == "alien_visitor"

    def test_state_preserved(self):
        """Explicit state on legacy entity is preserved."""
        ent = {
            "id": "door_1",
            "prefab": "dummy",
            "position": {"x": 1.0, "y": 1.0},
            "state": "locked",
        }
        result, _ = migrate_entity(ent)
        assert result["state"] == "locked"

    def test_state_defaults_to_default(self):
        """Missing state defaults to 'default'."""
        ent = {
            "id": "npc_1",
            "prefab": "npc",
            "position": {"x": 1.0, "y": 1.0},
        }
        result, _ = migrate_entity(ent)
        assert result["state"] == "default"

    def test_uid_placeholder_when_missing(self):
        """Missing uid gets -1 placeholder."""
        ent = {
            "id": "npc_1",
            "prefab": "npc",
            "position": {"x": 1.0, "y": 1.0},
        }
        result, _ = migrate_entity(ent)
        assert result["uid"] == -1

    def test_uid_preserved_when_present(self):
        """Existing uid is kept."""
        ent = {
            "id": "npc_1",
            "uid": 42,
            "prefab": "npc",
            "position": {"x": 1.0, "y": 1.0},
        }
        result, _ = migrate_entity(ent)
        assert result["uid"] == 42

    def test_pushable_and_persist_in_overrides(self):
        """Non-standard keys like 'pushable' end up in overrides."""
        ent = {
            "id": "dummy_bob",
            "prefab": "dummy",
            "position": {"x": 3.5, "y": 2.5},
            "pushable": {"friction": 4.0},
            "persist": {"uid": "dummy_bob"},
            "dialogue": {"bark": "Ow!"},
        }
        result, _ = migrate_entity(ent)
        ov = result["overrides"]
        assert ov["pushable"] == {"friction": 4.0}
        assert ov["persist"] == {"uid": "dummy_bob"}
        assert ov["dialogue"] == {"bark": "Ow!"}

    def test_angle_from_flat_x_y_entity(self):
        """Entity with flat x/y (editor format) + prefab migrates correctly."""
        ent = {
            "id": "barrel_1",
            "prefab": "barrel",
            "x": 5.5,
            "y": 3.5,
        }
        result, changed = migrate_entity(ent)
        assert changed
        assert result["x"] == 5.5
        assert result["y"] == 3.5
        # No facing → angle defaults to 0.0
        assert result["angle"] == 0.0

    def test_tile_entity_overrides(self):
        """tile_entity with loot_table ends up in overrides."""
        ent = {
            "id": "shelf_1",
            "prefab": "shelf",
            "position": {"x": 2.5, "y": 1.5},
            "tile_entity": {"tile_type": "container", "loot_table": "basic_chest"},
            "facing": {"direction": "up"},
        }
        result, _ = migrate_entity(ent)
        ov = result["overrides"]
        assert ov["tile_entity"]["loot_table"] == "basic_chest"
        assert result["angle"] == DIRECTION_TO_ANGLE["up"]


class TestIdempotency:
    """Verify the script is safe to run twice."""

    def test_double_migration(self):
        """Migrating already-migrated output produces no changes."""
        legacy = {
            "id": "shopkeeper",
            "prefab": "merchant",
            "position": {"x": 6.5, "y": 2.5},
            "facing": {"direction": "down"},
            "identity": {"name": "Shopkeeper"},
        }
        first, changed1 = migrate_entity(legacy)
        assert changed1

        second, changed2 = migrate_entity(first)
        assert not changed2
        assert second is first  # exact same object

    def test_triple_migration(self):
        """Three passes, all stable."""
        ent = {
            "id": "npc_1",
            "prefab": "npc",
            "position": {"x": 1.0, "y": 2.0},
            "sprite": {"color": [255, 0, 0]},
        }
        r1, c1 = migrate_entity(ent)
        r2, c2 = migrate_entity(r1)
        r3, c3 = migrate_entity(r2)
        assert c1 and not c2 and not c3
        assert r2 is r1
        assert r3 is r2


class TestPrefabMap:
    """Verify the mapping table is complete."""

    def test_all_legacy_prefabs_mapped(self):
        """Every known old prefab has a mapping."""
        expected = {
            "player", "dummy", "npc", "merchant", "villager", "beast",
            "container", "crop", "ground_item", "crate", "shelf",
            "barrel", "table", "chair", "lantern", "bookcase",
            "counter", "safe", "potted_plant",
        }
        assert set(PREFAB_TO_TYPE.keys()) == expected

    def test_direction_angles_sane(self):
        """Direction map covers all four directions with reasonable angles."""
        assert set(DIRECTION_TO_ANGLE.keys()) == {"up", "down", "left", "right"}
        for d, a in DIRECTION_TO_ANGLE.items():
            assert 0.0 <= a < 2 * math.pi, f"{d} = {a}"
