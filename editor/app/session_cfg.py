"""editor/app/session_cfg.py — Persist editor session state across launches.

Stores recent files, panel layout, window size, and camera bookmarks
in a JSON file at ``<project_root>/editor_session.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

_CFG_PATH = Path(__file__).resolve().parent.parent.parent / "editor_session.json"
_MAX_RECENT = 12


def _defaults() -> dict:
    return {
        "last_zone": "",
        "recent_zones": [],
        "left_panel_w": 280,
        "right_panel_w": 250,
        "window_w": 1600,
        "window_h": 900,
        "view_mode": "3d",
        "show_texture_browser": False,
        "camera_bookmarks": [],
    }


def load_session() -> dict:
    """Load session config, returning defaults for missing keys."""
    cfg = _defaults()
    if _CFG_PATH.exists():
        try:
            with open(_CFG_PATH, "r") as fh:
                stored = json.load(fh)
            cfg.update(stored)
        except Exception:  # noqa: BLE001
            pass
    return cfg


def save_session(cfg: dict) -> None:
    """Write session config to disk (best-effort, never raises)."""
    try:
        with open(_CFG_PATH, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:  # noqa: BLE001
        pass


def push_recent(cfg: dict, zone_name: str) -> None:
    """Add *zone_name* to the MRU list (most-recent first, deduped)."""
    if not zone_name or zone_name == "untitled":
        return
    recent = cfg.get("recent_zones", [])
    if zone_name in recent:
        recent.remove(zone_name)
    recent.insert(0, zone_name)
    cfg["recent_zones"] = recent[:_MAX_RECENT]
