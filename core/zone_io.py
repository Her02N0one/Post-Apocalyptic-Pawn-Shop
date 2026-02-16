"""core/zone_io.py — JSON zone file I/O.

Zone files are simple JSON dictionaries stored in ``zones/*.json``.

Schema
------
.. code-block:: json

    {
        "name":    "playground",
        "width":   30,
        "height":  20,
        "anchor":  [15.0, 10.0],
        "tiles":   [[6,6,6,...], ...],
        "portals": [
            {
                "tiles":       [[0, 15]],
                "target_zone": "other_zone",
                "target_pos":  [2, 15]
            }
        ],
        "entities": [
            {
                "id": "dummy_bob",
                ...component descriptor keys...
            }
        ]
    }

``tiles`` is a row-major 2-D array of tile-type IDs (see
``core.constants`` for the palette).

``portals`` define one-way links from specific tiles in *this* zone
to a landing position in another zone.  Two-way travel requires a
matching portal in the target zone's file.

``entities`` use the same descriptor format consumed by
``systems.engine.entity_factory.spawn_from_descriptor``.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

ZONES_DIR = Path(__file__).resolve().parent.parent / "zones"


# ── Read / write ─────────────────────────────────────────────────────

def load_zone_json(path: str | Path) -> dict[str, Any]:
    """Load a zone from a ``.json`` file and return the raw dict."""
    with open(path) as f:
        return json.load(f)


def save_zone_json(path: str | Path, data: dict[str, Any]) -> None:
    """Save a zone dict to a ``.json`` file (pretty-printed)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ── Discovery ────────────────────────────────────────────────────────

def discover_zone_files(dir_path: Path | None = None) -> dict[str, Path]:
    """Return ``{zone_name: path}`` for every ``.json`` file in *dir_path*.

    Zone name is the file stem (``playground.json`` → ``"playground"``).
    """
    d = dir_path or ZONES_DIR
    d = Path(d)
    if not d.exists():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.json"))}


# ── Helpers ──────────────────────────────────────────────────────────

def extract_portals(zone_data: dict) -> dict[tuple[int, int], dict]:
    """Build a ``{(row, col): target_info}`` lookup from a zone's portals.

    Returns ``{(r, c): {"zone": target_zone, "r": row, "c": col}}``.
    """
    out: dict[tuple[int, int], dict] = {}
    for portal in zone_data.get("portals", []):
        target_zone = portal.get("target_zone", "")
        tp = portal.get("target_pos", [0, 0])
        target_r, target_c = float(tp[0]), float(tp[1])
        for tile in portal.get("tiles", []):
            r, c = int(tile[0]), int(tile[1])
            out[(r, c)] = {
                "zone": target_zone,
                "r": target_r,
                "c": target_c,
            }
    return out
