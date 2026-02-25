#!/usr/bin/env python3
"""Batch-convert all zones/*.json files to zones/*.zone binary format.

Usage:  python -m tools.migrate_json_zones [--delete-json]

The original JSON files are kept by default unless --delete-json is given.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is importable
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.zones import GameRegistry
from core.paths import ZONES_DIR
from core.zones import Zone, Portal, OverlayWall


def _load_zone_from_json(path: Path) -> Zone:
    """Load a Zone from a legacy JSON file."""
    with open(path) as f:
        d = json.load(f)

    name = d.get("name", path.stem)
    tiles = d.get("tiles", [])
    H = len(tiles)
    W = len(tiles[0]) if H else 0

    def _grid(key, default, h, w):
        g = d.get(key, [])
        if g and len(g) == h:
            return g
        return [[default] * w for _ in range(h)]

    def _grid4(key, default, h, w):
        g = d.get(key, [])
        if g and len(g) == h:
            return g
        return [[[default] * 4 for _ in range(w)] for _ in range(h)]

    def _seg_grid(key, h, w):
        g = d.get(key, [])
        if g and len(g) == h:
            return g
        return [[[[], [], [], []] for _ in range(w)] for _ in range(h)]

    # Parse portals
    portals: list[Portal] = []
    for pd in d.get("portals", []):
        tiles_list = []
        for t in pd.get("tiles", []):
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                tiles_list.append((int(t[0]), int(t[1])))
        tp = pd.get("target_pos", [0, 0])
        portals.append(Portal(
            tiles=tiles_list,
            target_zone=pd.get("target_zone", ""),
            target_row=float(tp[0]) if len(tp) > 0 else 0.0,
            target_col=float(tp[1]) if len(tp) > 1 else 0.0,
            exit_direction=pd.get("exit_direction", "up"),
        ))

    # Parse overlay walls
    overlay_walls: list[OverlayWall] = []
    for ow in d.get("overlay_walls", []):
        overlay_walls.append(OverlayWall(
            x1=float(ow.get("x1", 0)), y1=float(ow.get("y1", 0)),
            x2=float(ow.get("x2", 0)), y2=float(ow.get("y2", 0)),
            texture=str(ow.get("texture", "brick_wall")),
            height_scale=float(ow.get("height_scale", 1.0)),
            transparent=bool(ow.get("transparent", False)),
            blocks=bool(ow.get("blocks", True)),
        ))

    anchor = d.get("anchor", [H / 2.0, W / 2.0])
    if not isinstance(anchor, (list, tuple)) or len(anchor) < 2:
        anchor = [H / 2.0, W / 2.0]

    return Zone(
        name=name,
        width=W,
        height=H,
        anchor=(float(anchor[0]), float(anchor[1])),
        tiles=tiles,
        rotations=_grid("rotations", 0, H, W),
        portals=portals,
        entities=d.get("entities", []),
        first_person=bool(d.get("first_person", False)),
        floor_heights=_grid("floor_heights", 0.0, H, W),
        ceil_heights=_grid("ceil_heights", 10.0, H, W),
        floor_textures=_grid("floor_textures", "", H, W),
        ceil_textures=_grid("ceil_textures", "", H, W),
        wall_textures=_grid("wall_textures", "", H, W),
        face_textures=_grid4("face_textures", "", H, W),
        light_levels=_grid("light_levels", 1.0, H, W),
        wall_segments=_seg_grid("wall_segments", H, W),
        floor_step_textures=_grid4("floor_step_textures", "", H, W),
        ceil_step_textures=_grid4("ceil_step_textures", "", H, W),
        floor_step_segments=_seg_grid("floor_step_segments", H, W),
        ceil_step_segments=_seg_grid("ceil_step_segments", H, W),
        upper_wall_height=_grid("upper_wall_height", 0.0, H, W),
        overlay_walls=overlay_walls,
    )


def main() -> None:
    delete_json = "--delete-json" in sys.argv

    registry = GameRegistry()
    json_files = sorted(ZONES_DIR.glob("*.json"))
    if not json_files:
        print("No .json zone files found in", ZONES_DIR)
        return

    ok, fail = 0, 0
    for jp in json_files:
        out = jp.with_suffix(".zone")
        try:
            zone = _load_zone_from_json(jp)
            zone.save_to_file(out, registry)
            ok += 1
            print(f"  OK  {jp.name} → {out.name}")
            if delete_json:
                jp.unlink()
        except Exception as exc:
            fail += 1
            print(f"  FAIL {jp.name}: {exc}")

    print(f"\nConverted {ok}/{ok + fail} zones.")
    if fail:
        print(f"  {fail} failed — JSON files kept.")


if __name__ == "__main__":
    main()
