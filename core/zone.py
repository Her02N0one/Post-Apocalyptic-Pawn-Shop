"""core/zone.py — NBT-backed zone maps, anchors, portals, and helpers.

This loader uses .nbt files placed in `zones/` for tile-maps and
`data/portals.toml` for interzone portal definitions.  Portals are
bidirectional links that the player (and abstract NPCs) use to
travel between zones.
"""
from __future__ import annotations
import random
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from core.nbt import load_zone_nbt
except Exception:
    load_zone_nbt = None


ZONES_DIR = Path("zones")


# In-memory caches populated by `load_zones_from_disk()` at import time.
ZONE_MAPS: dict[str, list[list[int]]] = {}
ZONE_ANCHORS: dict[str, tuple[float, float]] = {}
"""
ZONE_TELEPORTERS maps zone -> {(row,col): target}
Where target is either a zone-name string (legacy) or a dict {"zone":zone, "r":row, "c":col}
"""
ZONE_TELEPORTERS: dict[str, dict[tuple[int, int], object]] = {}
ZONE_SPAWNS: dict[str, list[dict]] = {}


# ── Portal system ────────────────────────────────────────────────────

@dataclass
class PortalSide:
    """One endpoint of a bidirectional portal."""
    zone: str
    tiles: list[tuple[int, int]]      # teleporter tile positions in this zone
    spawn: tuple[float, float]        # (row, col) landing position when arriving
    subzone: str = ""                 # linked subzone graph node id


@dataclass
class Portal:
    """Bidirectional interzone connection."""
    id: str
    side_a: PortalSide
    side_b: PortalSide


ZONE_PORTALS: list[Portal] = []
# zone -> {(row, col): (target_zone, spawn_row, spawn_col, portal_id)}
_PORTAL_LOOKUP: dict[str, dict[tuple[int, int], tuple[str, float, float, str]]] = {}


def _parse_teleporters(raw: dict) -> dict[tuple[int, int], object]:
    out = {}
    for k, v in raw.items():
        if isinstance(k, str) and "," in k:
            try:
                r, c = k.split(",")
                out[(int(r.strip()), int(c.strip()))] = v
            except Exception:
                continue
        elif isinstance(k, (list, tuple)) and len(k) == 2:
            out[(int(k[0]), int(k[1]))] = v
    return out


def _load_nbt_file(path: Path):
    if load_zone_nbt is None:
        return
    try:
        obj = load_zone_nbt(path)
    except Exception:
        return
    name = obj.get("name") or path.stem
    tiles = obj.get("tiles")
    if tiles:
        ZONE_MAPS[name] = tiles
    anchors = obj.get("anchors")
    if anchors and isinstance(anchors, dict):
        a = anchors.get(name) or anchors.get("default")
        if isinstance(a, (list, tuple)) and len(a) == 2:
            ZONE_ANCHORS[name] = (float(a[0]), float(a[1]))
    tele = obj.get("teleporters") or {}
    if isinstance(tele, dict):
        ZONE_TELEPORTERS[name] = _parse_teleporters(tele)
    spawns = obj.get("spawns") or obj.get("entities") or []
    if isinstance(spawns, list) and spawns:
        ZONE_SPAWNS[name] = spawns


def load_zones_from_disk(dir_path: Optional[Path] = None):
    """Load all .nbt zone files from `zones/` into memory.

    This intentionally ignores JSON files; the editor should write NBT.
    """
    if dir_path is None:
        dir_path = ZONES_DIR
    dir_path = Path(dir_path)
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        return

    for p in sorted(dir_path.glob("*.nbt")):
        _load_nbt_file(p)


def is_passable(zone: str, x: float, y: float) -> bool:
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return True
    r = int(y)
    c = int(x)
    if r < 0 or c < 0 or r >= len(tiles) or c >= len(tiles[0]):
        return False
    from core.constants import TILE_WALL
    return tiles[r][c] != TILE_WALL


def has_line_of_sight(zone: str, x1: float, y1: float,
                      x2: float, y2: float) -> bool:
    """Return True if no wall tile blocks the line from (x1,y1) to (x2,y2).

    Uses a DDA (digital-differential-analyzer) grid walk so every
    tile the ray passes through is tested.
    """
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return True
    rows = len(tiles)
    cols = len(tiles[0]) if rows else 0
    if rows == 0 or cols == 0:
        return True

    from core.constants import TILE_WALL

    dx = x2 - x1
    dy = y2 - y1
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < 0.01:
        return True

    # Step size: half a tile for accuracy
    steps = int(dist * 2.5) + 1
    sx = dx / steps
    sy = dy / steps

    prev_c, prev_r = -1, -1
    cx, cy = x1, y1
    for _ in range(steps + 1):
        c = int(cx)
        r = int(cy)
        if c != prev_c or r != prev_r:
            if r < 0 or r >= rows or c < 0 or c >= cols:
                return False
            if tiles[r][c] == TILE_WALL:
                return False
            prev_c, prev_r = c, r
        cx += sx
        cy += sy

    return True


def random_passable_spot(zone: str, center_x: float, center_y: float, radius: float, attempts: int = 64):
    for _ in range(attempts):
        dx = random.uniform(-radius / 2.0, radius / 2.0)
        dy = random.uniform(-radius / 2.0, radius / 2.0)
        x = center_x + dx
        y = center_y + dy
        if is_passable(zone, x, y):
            return x, y
    return None


# ── Portal loading / saving ──────────────────────────────────────────

def load_portals(path: Path | None = None):
    """Load portal definitions from ``data/portals.toml``."""
    if path is None:
        path = Path("data/portals.toml")
    if not path.exists():
        return
    with open(path, "rb") as f:
        data = tomllib.load(f)
    ZONE_PORTALS.clear()
    _PORTAL_LOOKUP.clear()
    for p in data.get("portal", []):
        portal = Portal(
            id=p["id"],
            side_a=PortalSide(
                zone=p["zone_a"],
                tiles=[(int(t[0]), int(t[1])) for t in p.get("tiles_a", [])],
                spawn=(float(p["spawn_a"][0]), float(p["spawn_a"][1])),
                subzone=p.get("subzone_a", ""),
            ),
            side_b=PortalSide(
                zone=p["zone_b"],
                tiles=[(int(t[0]), int(t[1])) for t in p.get("tiles_b", [])],
                spawn=(float(p["spawn_b"][0]), float(p["spawn_b"][1])),
                subzone=p.get("subzone_b", ""),
            ),
        )
        ZONE_PORTALS.append(portal)
        # Side-A tiles → teleports to side-B spawn
        for r, c in portal.side_a.tiles:
            _PORTAL_LOOKUP.setdefault(portal.side_a.zone, {})[(r, c)] = (
                portal.side_b.zone, portal.side_b.spawn[0],
                portal.side_b.spawn[1], portal.id,
            )
        # Side-B tiles → teleports to side-A spawn
        for r, c in portal.side_b.tiles:
            _PORTAL_LOOKUP.setdefault(portal.side_b.zone, {})[(r, c)] = (
                portal.side_a.zone, portal.side_a.spawn[0],
                portal.side_a.spawn[1], portal.id,
            )
    print(f"[PORTAL] loaded {len(ZONE_PORTALS)} portals")


def save_portals(path: Path | None = None):
    """Write current portal definitions to ``data/portals.toml``."""
    if path is None:
        path = Path("data/portals.toml")
    lines: list[str] = [
        "# data/portals.toml \u2014 Interzone portal definitions.",
    ]
    for portal in ZONE_PORTALS:
        lines.append("")
        lines.append("[[portal]]")
        lines.append(f'id = "{portal.id}"')
        lines.append(f'zone_a = "{portal.side_a.zone}"')
        ta = ", ".join(f"[{r}, {c}]" for r, c in portal.side_a.tiles)
        lines.append(f"tiles_a = [{ta}]")
        sr, sc = portal.side_a.spawn
        lines.append(f"spawn_a = [{int(sr)}, {int(sc)}]")
        lines.append(f'subzone_a = "{portal.side_a.subzone}"')
        lines.append(f'zone_b = "{portal.side_b.zone}"')
        tb = ", ".join(f"[{r}, {c}]" for r, c in portal.side_b.tiles)
        lines.append(f"tiles_b = [{tb}]")
        sr2, sc2 = portal.side_b.spawn
        lines.append(f"spawn_b = [{int(sr2)}, {int(sc2)}]")
        lines.append(f'subzone_b = "{portal.side_b.subzone}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    print(f"[PORTAL] saved {len(ZONE_PORTALS)} portals to {path}")


# ── Safe-spawn resolution ────────────────────────────────────────────

def find_safe_spawn(zone: str, row: float, col: float) -> tuple[float, float]:
    """Return ``(x, y)`` game-position near tile *(row, col)* that
    avoids wall overlap for a 0.8\u00d70.8 hitbox.

    Returns ``(col + offset, row + offset)`` — i.e. *(x, y)* order.
    """
    tiles = ZONE_MAPS.get(zone)
    if not tiles:
        return col + 0.1, row + 0.1
    from core.collision import aabb_hits_wall as _aabb_hits_wall, HITBOX_W, HITBOX_H
    map_h = len(tiles)
    map_w = len(tiles[0]) if tiles else 0
    off = (1.0 - HITBOX_W) / 2.0          # 0.1 for 0.8 hitbox
    x0, y0 = col + off, row + off
    if not _aabb_hits_wall(x0, y0, HITBOX_W, HITBOX_H, map_h, map_w, tiles):
        return x0, y0
    # Expanding ring search
    for radius in range(1, 6):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue
                tx = col + dc + off
                ty = row + dr + off
                if tx < 0 or ty < 0:
                    continue
                if not _aabb_hits_wall(tx, ty, HITBOX_W, HITBOX_H,
                                      map_h, map_w, tiles):
                    return tx, ty
    return x0, y0


# ── Portal helpers ───────────────────────────────────────────────────

def get_portal_for_tile(zone: str, r: int, c: int) -> Portal | None:
    """Return the Portal that owns tile *(r, c)* in *zone*, or None."""
    for portal in ZONE_PORTALS:
        if portal.side_a.zone == zone and (r, c) in portal.side_a.tiles:
            return portal
        if portal.side_b.zone == zone and (r, c) in portal.side_b.tiles:
            return portal
    return None


def get_portal_sides(portal: Portal, zone: str
                     ) -> tuple[PortalSide, PortalSide]:
    """Return *(this_side, other_side)* relative to *zone*."""
    if portal.side_a.zone == zone:
        return portal.side_a, portal.side_b
    return portal.side_b, portal.side_a


def portal_lookup_for_zone(zone: str
                           ) -> dict[tuple[int, int],
                                     tuple[str, float, float, str]]:
    """Return the portal lookup dict for a zone (or empty)."""
    return _PORTAL_LOOKUP.get(zone, {})


# NOTE: Call load_zones_from_disk() explicitly in main.py before scene creation.
# Removed auto-load-on-import to avoid side effects and enable unit testing.
