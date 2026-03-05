"""core/paths.py — Single source of truth for project directory paths.

Every module that needs to locate zones/, data/, assets/, templates/,
or the project root should import from here rather than computing
paths locally.

    from core.paths import ZONES_DIR, DATA_DIR, ASSETS_DIR
"""

from __future__ import annotations

from pathlib import Path

# Resolved once at import time — safe for frozen / installed layouts.
PROJECT_ROOT  = Path(__file__).resolve().parent.parent

# ── Top-level directories ────────────────────────────────────────
ZONES_DIR     = PROJECT_ROOT / "zones"
DATA_DIR      = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
ROOMS_DIR     = TEMPLATES_DIR / "rooms"
SAVES_DIR     = PROJECT_ROOT / "saves"
ASSETS_DIR    = PROJECT_ROOT / "assets"
LOGS_DIR      = PROJECT_ROOT / "logs"

# ── Assets sub-paths ─────────────────────────────────────────────
TEXTURES_DIR      = ASSETS_DIR / "textures"
TILE_TEX_DIR      = TEXTURES_DIR / "tiles"
SKYBOXES_DIR      = TEXTURES_DIR / "skyboxes"
BILLBOARDS_DIR    = TEXTURES_DIR / "billboards"
MODELS_DIR        = ASSETS_DIR / "models"
TILES_TOML_DIR    = MODELS_DIR / "tiles"

# ── Data sub-paths ───────────────────────────────────────────────
LOOT_TABLES_PATH  = DATA_DIR / "loot_tables.toml"
ITEMS_PATH        = DATA_DIR / "items.toml"

CUSTOM_ENTITIES_PATH = DATA_DIR / "custom_entities.toml"
