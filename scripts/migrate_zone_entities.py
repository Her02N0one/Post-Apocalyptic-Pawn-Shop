#!/usr/bin/env python3
"""scripts/migrate_zone_entities.py — Phase 2 zone entity migration.

Converts entity descriptors in ``.zone`` files from the legacy format
to the unified format:

**Legacy:**
    {"id": "shop", "prefab": "merchant", "position": {"x": 6, "y": 2},
     "identity": {"name": "Shopkeeper"}, "facing": {"direction": "down"}}

**Unified:**
    {"id": "shop", "type": "merchant_npc", "x": 6.0, "y": 2.0,
     "angle": 4.712, "state": "default",
     "overrides": {"identity": {"name": "Shopkeeper"}}}

Idempotency: descriptors that already have ``"type"`` and no ``"prefab"``
are left untouched.  Safe to run multiple times.

Usage:
    python scripts/migrate_zone_entities.py [--dry-run] [--zone NAME]

    --dry-run   Print changes without writing files.
    --zone NAME Only process the named zone (without .zone extension).
"""

from __future__ import annotations

import argparse
import math
import shutil
import struct
import sys
from pathlib import Path

# Add project root so we can import format constants.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import msgpack
from core.zones.format import (
    ZONE_MAGIC, HEADER_FMT, HEADER_SIZE,
    CHUNK_HEADER_FMT, CHUNK_HEADER_SIZE, CHUNK_ENTY,
)

ZONES_DIR = _PROJECT_ROOT / "zones"
BACKUP_DIR = _PROJECT_ROOT / "zones" / "_backups"

# ── Prefab → type ID mapping ────────────────────────────────────────
# Matches _LEGACY_PREFAB_MAP in systems/spawner.py.

PREFAB_TO_TYPE: dict[str, str] = {
    "player":       "player",
    "dummy":        "dummy",
    "npc":          "survivor_npc",
    "merchant":     "merchant_npc",
    "villager":     "villager_npc",
    "beast":        "beast",
    "container":    "container",
    "crop":         "crop",
    "ground_item":  "ground_item",
    "crate":        "wooden_crate",
    "shelf":        "shelf",
    "barrel":       "barrel",
    "table":        "table",
    "chair":        "chair",
    "lantern":      "lantern",
    "bookcase":     "bookcase",
    "counter":      "counter",
    "safe":         "safe",
    "potted_plant": "potted_plant",
}

# ── Direction → angle (radians) mapping ──────────────────────────────
# Convention: 0 = east, π/2 = north, π = west, 3π/2 = south.

DIRECTION_TO_ANGLE: dict[str, float] = {
    "right": 0.0,
    "up":    math.pi / 2,
    "left":  math.pi,
    "down":  3 * math.pi / 2,
}

# Keys that are per-entity metadata, NOT component overrides.
_META_KEYS = {"id", "uid", "type", "prefab", "position", "x", "y",
              "angle", "state", "overrides", "properties"}


# ── Single-entity migration ─────────────────────────────────────────

def migrate_entity(ent: dict) -> tuple[dict, bool]:
    """Migrate one entity descriptor.  Returns (new_dict, changed).

    Idempotent: if the entity already has ``"type"`` and no ``"prefab"``,
    it's returned unchanged.
    """
    # ── Already migrated? ─────────────────────────────────────────
    if "type" in ent and "prefab" not in ent:
        # Also handle "properties" → "overrides" rename if needed.
        if "properties" in ent and "overrides" not in ent:
            new = dict(ent)
            new["overrides"] = new.pop("properties")
            return new, True
        return ent, False

    # ── Needs migration ───────────────────────────────────────────
    prefab = ent.get("prefab", "")
    type_id = PREFAB_TO_TYPE.get(prefab, prefab)

    new: dict = {}

    # id
    new["id"] = ent.get("id", "")

    # uid — assign -1 as placeholder if missing; the editor will
    # reassign on next load.
    new["uid"] = ent.get("uid", -1)

    # type (replaces prefab)
    new["type"] = type_id

    # Position: flatten nested → top-level x/y
    pos = ent.get("position", {})
    if "x" in ent:
        new["x"] = float(ent["x"])
        new["y"] = float(ent["y"])
    elif isinstance(pos, dict):
        new["x"] = float(pos.get("x", 0.0))
        new["y"] = float(pos.get("y", 0.0))
    else:
        new["x"] = 0.0
        new["y"] = 0.0

    # Angle: convert facing direction → radians
    facing = ent.get("facing", {})
    if isinstance(facing, dict) and "direction" in facing:
        direction = facing["direction"]
        new["angle"] = DIRECTION_TO_ANGLE.get(direction, 3 * math.pi / 2)
    else:
        new["angle"] = ent.get("angle", 0.0)

    # State
    new["state"] = ent.get("state", "default")

    # Overrides: collect all dict-valued keys that aren't metadata
    overrides: dict = {}
    for k, v in ent.items():
        if k in _META_KEYS:
            continue
        if isinstance(v, dict):
            overrides[k] = v
        # Non-dict top-level keys (e.g. "pushable" as a scalar) — skip,
        # they don't map to the component sub-table pattern.

    # If original had "properties" or "overrides", merge those too
    if "properties" in ent and isinstance(ent["properties"], dict):
        for k, v in ent["properties"].items():
            if isinstance(v, dict):
                if k in overrides:
                    overrides[k].update(v)
                else:
                    overrides[k] = v
    if "overrides" in ent and isinstance(ent["overrides"], dict):
        for k, v in ent["overrides"].items():
            if isinstance(v, dict):
                if k in overrides:
                    overrides[k].update(v)
                else:
                    overrides[k] = v

    # Don't store facing in overrides — it was converted to angle
    overrides.pop("facing", None)

    new["overrides"] = overrides

    return new, True


# ── Zone file I/O (chunk-level, no GameRegistry needed) ──────────────

def read_zone_chunks(filepath: Path) -> tuple[bytes, list[tuple[int, bytes]]]:
    """Read a zone file into (header_bytes, [(chunk_id, chunk_data), ...])."""
    with open(filepath, "rb") as f:
        header = f.read(HEADER_SIZE)
        magic = struct.unpack_from(HEADER_FMT, header)[0]
        if magic != ZONE_MAGIC:
            raise ValueError(f"Bad magic in {filepath}")

        chunks: list[tuple[int, bytes]] = []
        while True:
            ch = f.read(CHUNK_HEADER_SIZE)
            if len(ch) < CHUNK_HEADER_SIZE:
                break
            cid, clen = struct.unpack(CHUNK_HEADER_FMT, ch)
            data = f.read(clen)
            chunks.append((cid, data))

    return header, chunks


def write_zone_chunks(filepath: Path, header: bytes,
                      chunks: list[tuple[int, bytes]]) -> None:
    """Write a zone file from header + chunk list."""
    with open(filepath, "wb") as f:
        f.write(header)
        for cid, data in chunks:
            f.write(struct.pack(CHUNK_HEADER_FMT, cid, len(data)))
            f.write(data)


# ── Main migration logic ────────────────────────────────────────────

def migrate_zone_file(filepath: Path, dry_run: bool = False) -> int:
    """Migrate entities in a single zone file.

    Returns the number of entities changed.
    """
    header, chunks = read_zone_chunks(filepath)

    changed_count = 0
    new_chunks: list[tuple[int, bytes]] = []

    for cid, data in chunks:
        if cid != CHUNK_ENTY:
            new_chunks.append((cid, data))
            continue

        # Decode ENTY payload
        payload = msgpack.unpackb(data, raw=False)
        entities = payload.get("entities", [])
        new_entities = []

        for ent in entities:
            new_ent, changed = migrate_entity(ent)
            new_entities.append(new_ent)
            if changed:
                changed_count += 1

        payload["entities"] = new_entities
        new_data = msgpack.packb(payload, use_bin_type=True)
        new_chunks.append((cid, new_data))

    if changed_count > 0 and not dry_run:
        # Backup original
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / filepath.name
        shutil.copy2(filepath, backup_path)

        # Write migrated file
        write_zone_chunks(filepath, header, new_chunks)

    return changed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate zone entity descriptors to unified format.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing files.")
    parser.add_argument("--zone", type=str, default=None,
                        help="Only process this zone (name without .zone).")
    args = parser.parse_args()

    if args.zone:
        zone_files = [ZONES_DIR / f"{args.zone}.zone"]
        if not zone_files[0].exists():
            print(f"Zone file not found: {zone_files[0]}")
            sys.exit(1)
    else:
        zone_files = sorted(ZONES_DIR.glob("*.zone"))

    total_changed = 0
    total_files = 0

    for zf in zone_files:
        n = migrate_zone_file(zf, dry_run=args.dry_run)
        if n > 0:
            action = "would migrate" if args.dry_run else "migrated"
            print(f"  {zf.name}: {action} {n} entities")
            total_changed += n
            total_files += 1
        else:
            print(f"  {zf.name}: no changes needed")

    action = "Would migrate" if args.dry_run else "Migrated"
    print(f"\n{action} {total_changed} entities across {total_files} files.")


if __name__ == "__main__":
    main()
