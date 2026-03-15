"""core.zones.migration — Zone format version + migration pipeline.

Provides a versioned migration system that upgrades old zone ENTY
payloads to the current schema.  Each migration function handles one
version bump and is registered via :func:`register_migration`.

The ``ZONE_SCHEMA_VERSION`` constant is embedded in saved zone files.
On load, if the stored version is older than the current one, the
migration pipeline applies each upgrade step in sequence.

Usage (in io.py)::

    enty = msgpack.unpackb(raw, raw=False)
    enty = apply_migrations(enty)  # upgrades to current version
"""

from __future__ import annotations

from typing import Any, Callable

# ═══════════════════════════════════════════════════════════════════
#  Current schema version
# ═══════════════════════════════════════════════════════════════════

# Bump this when adding a new migration function.
# v0 = original unversioned format
# v1 = ensure_uids applied, floor_slope_div persisted, typed objects
# v2 = curve "transparent" key → flags bit-field
ZONE_SCHEMA_VERSION: int = 2


# ═══════════════════════════════════════════════════════════════════
#  Migration registry
# ═══════════════════════════════════════════════════════════════════

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]

_MIGRATIONS: dict[int, MigrationFn] = {}


def register_migration(from_version: int) -> Callable:
    """Decorator — register a migration from ``from_version`` → ``from_version + 1``."""
    def decorator(fn: MigrationFn) -> MigrationFn:
        _MIGRATIONS[from_version] = fn
        return fn
    return decorator


def apply_migrations(enty: dict[str, Any]) -> dict[str, Any]:
    """Apply all pending migrations to an ENTY payload.

    Reads ``enty["schema_version"]`` (default 0 for legacy files),
    then applies each registered migration in order until the payload
    is at ``ZONE_SCHEMA_VERSION``.

    Returns the (possibly mutated) enty dict.
    """
    version = enty.get("schema_version", 0)

    while version < ZONE_SCHEMA_VERSION:
        fn = _MIGRATIONS.get(version)
        if fn is None:
            raise ValueError(
                f"No migration registered for zone schema v{version} → v{version + 1}. "
                f"Current version is {ZONE_SCHEMA_VERSION}."
            )
        enty = fn(enty)
        version += 1
        enty["schema_version"] = version

    return enty


# ═══════════════════════════════════════════════════════════════════
#  Migration: v0 → v1
# ═══════════════════════════════════════════════════════════════════

@register_migration(0)
def _migrate_v0_to_v1(enty: dict[str, Any]) -> dict[str, Any]:
    """Upgrade unversioned zone data to schema v1.

    Changes:
    - Ensure ``floor_slope_div`` is present (was silently lost in v0).
    - Add ``schema_version`` key.
    - Backfill missing default grids that were implicit in v0.
    """
    # floor_slope_div was written to the ENTY payload in save_binary_zone
    # but the load path in io.py forgot to read it (it only appeared in
    # setdefault).  Ensure it's present.
    enty.setdefault("floor_slope_div", [])

    # Backfill any other keys that may be missing in very old files
    _DEFAULTS: dict[str, Any] = {
        "floor_slope_dx": [],
        "floor_slope_dy": [],
        "floor2_heights": [],
        "ceil2_heights": [],
        "floor2_textures": [],
        "ceil2_textures": [],
        "upper_wall_height2": [],
        "fog_density": [],
        "fog_color": [],
        "render_portals": [],
        "skybox": "",
        "sky_color": [],
        "next_uid": 1,
    }
    for key, default in _DEFAULTS.items():
        enty.setdefault(key, default)

    return enty


# ═══════════════════════════════════════════════════════════════════
#  Migration: v1 → v2  (curve "transparent" → flags bit-field)
# ═══════════════════════════════════════════════════════════════════

_CF_TRANSPARENT: int = 1  # bit 0


@register_migration(1)
def _migrate_v1_to_v2(enty: dict[str, Any]) -> dict[str, Any]:
    """Upgrade v1 → v2: convert curve ``"transparent"`` to ``"flags"`` bit.

    Before v2, the renderer read a boolean ``"transparent"`` key on each
    curve dict.  Now it reads the ``"flags"`` integer.  This migration
    folds any legacy ``"transparent": true`` into ``flags |= 1`` and
    removes the obsolete key.
    """
    for cv in enty.get("curves", []):
        if cv.get("transparent", False):
            cv["flags"] = cv.get("flags", 0) | _CF_TRANSPARENT
        cv.pop("transparent", None)
    return enty
