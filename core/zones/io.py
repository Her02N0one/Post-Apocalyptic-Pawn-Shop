"""core/zone_io.py — Binary .zone file reader and writer.

Serialises a :class:`~core.zones.Zone` into a compact, chunked binary
format using the constants defined in :mod:`core.zone_format`, and
deserialises ``.zone`` files back into numpy arrays (plus entities and
portals via msgpack).

File layout (see :mod:`core.zone_format` for the full spec)::

    ┌────────────────────────────────┐
    │  Global Header (12 B)          │  magic · version · flags · W · H
    ├────────────────────────────────┤
    │  NAVI chunk  —  uint16[H,W]   │  navigation bitmasks
    │  ELEV chunk  —  float32[H,W]  │  floor_z ‖ ceil_z  (concatenated)
    │  RNDR chunk  —  uint16[H,W,6] │  textures ‖ float32[H,W] lights
    │  ENTY chunk  —  msgpack blob  │  entities + portals + overlay_walls
    └────────────────────────────────┘

Usage
-----
::

    from core.zone_io import save_binary_zone, load_binary_zone

    # Save
    save_binary_zone(zone, "zones/pawn_shop.zone", registry)

    # Load (full)
    data = load_binary_zone("zones/pawn_shop.zone")

    # Load (simulation only — skips RNDR chunk)
    data = load_binary_zone("zones/pawn_shop.zone", sim_only=True)
"""

from __future__ import annotations

import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any

import msgpack
import numpy as np

from core.zones.game_registry import GameRegistry
from core.zones.compiler import compile_zone_to_arrays
from core.zones.format import (
    ZONE_MAGIC,
    ZONE_VERSION,
    HEADER_FMT,
    HEADER_SIZE,
    CHUNK_HEADER_FMT,
    CHUNK_HEADER_SIZE,
    CHUNK_NAVI,
    CHUNK_ELEV,
    CHUNK_RNDR,
    CHUNK_ENTY,
    chunk_name,
)
from core.zones.zone import Zone


# ═══════════════════════════════════════════════════════════════════
#  Errors
# ═══════════════════════════════════════════════════════════════════

class ZoneIOError(Exception):
    """Raised on any binary zone I/O failure."""


# ═══════════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════════

def _write_chunk(f, chunk_id: int, payload: bytes) -> None:
    """Write a chunk header + payload to an open binary file."""
    f.write(struct.pack(CHUNK_HEADER_FMT, chunk_id, len(payload)))
    f.write(payload)


def _portals_to_dicts(zone: Zone) -> list[dict[str, Any]]:
    """Serialise Portal dataclasses into plain dicts for msgpack."""
    out: list[dict[str, Any]] = []
    for p in zone.portals:
        out.append({
            "tiles": [list(t) for t in p.tiles],
            "target_zone": p.target_zone,
            "target_row": p.target_row,
            "target_col": p.target_col,
            "exit_direction": p.exit_direction,
        })
    return out


def _overlay_walls_to_dicts(zone: Zone) -> list[dict[str, Any]]:
    """Serialise OverlayWall dataclasses into plain dicts for msgpack."""
    return [asdict(ow) for ow in zone.overlay_walls]


# ═══════════════════════════════════════════════════════════════════
#  save_binary_zone
# ═══════════════════════════════════════════════════════════════════

def save_binary_zone(
    zone: Zone,
    filepath: str | Path,
    registry: GameRegistry,
) -> None:
    """Compile *zone* and write it as a binary ``.zone`` file.

    Parameters
    ----------
    zone : Zone
        The source zone (loaded from JSON or built in the editor).
    filepath : str | Path
        Destination file path.  Parent directories must exist.
    registry : GameRegistry
        Game-wide asset registry.  The ``"texture"`` namespace will be
        populated with every texture the zone references.

    Raises
    ------
    ZoneIOError
        If the file cannot be written.
    """
    filepath = Path(filepath)

    cz = compile_zone_to_arrays(zone, registry)
    W, H = cz.width, cz.height

    try:
        with open(filepath, "wb") as f:
            # ── Global header ─────────────────────────────────────
            f.write(struct.pack(
                HEADER_FMT,
                ZONE_MAGIC,
                ZONE_VERSION,
                0,          # flags — reserved
                W,
                H,
            ))

            # ── NAVI chunk ────────────────────────────────────────
            navi_bytes = cz.navi_grid.tobytes()
            _write_chunk(f, CHUNK_NAVI, navi_bytes)

            # ── ELEV chunk ────────────────────────────────────────
            elev_bytes = cz.floor_z.tobytes() + cz.ceil_z.tobytes()
            _write_chunk(f, CHUNK_ELEV, elev_bytes)

            # ── RNDR chunk ────────────────────────────────────────
            rndr_bytes = cz.textures.tobytes() + cz.light_levels.tobytes()
            _write_chunk(f, CHUNK_RNDR, rndr_bytes)

            # ── ENTY chunk ────────────────────────────────────────
            # Stores both game-critical data (entities, portals) and
            # raw editor grids so a full Zone can be reconstructed on
            # load without needing the GameRegistry.
            enty_payload = {
                # Game data
                "entities": zone.entities,
                "portals": _portals_to_dicts(zone),
                "overlay_walls": _overlay_walls_to_dicts(zone),
                "name": zone.name,
                "first_person": zone.first_person,
                "anchor": list(zone.anchor),
                # Raw editor grids (needed to reconstruct editable Zone)
                "tiles": zone.tiles,
                "rotations": zone.rotations,
                "floor_textures": zone.floor_textures,
                "ceil_textures": zone.ceil_textures,
                "wall_textures": zone.wall_textures,
                "face_textures": zone.face_textures,
                "light_levels": zone.light_levels,
                "wall_segments": zone.wall_segments,
                "floor_step_textures": zone.floor_step_textures,
                "ceil_step_textures": zone.ceil_step_textures,
                "floor_step_segments": zone.floor_step_segments,
                "ceil_step_segments": zone.ceil_step_segments,
                "upper_wall_height": zone.upper_wall_height,
                "boxes": zone.boxes,
                "quads": zone.quads,
                "reflect_map": zone.reflect_map,
                "curves": zone.curves,
                "floor_slope_dx": zone.floor_slope_dx,
                "floor_slope_dy": zone.floor_slope_dy,
                "floor_slope_div": zone.floor_slope_div,
                "floor2_heights": zone.floor2_heights,
                "ceil2_heights": zone.ceil2_heights,
                "floor2_textures": zone.floor2_textures,
                "ceil2_textures": zone.ceil2_textures,
                "upper_wall_height2": zone.upper_wall_height2,
                "fog_density": zone.fog_density,
                "fog_color": zone.fog_color,
                "render_portals": zone.render_portals,
                "skybox": zone.skybox,
                "sky_color": list(zone.sky_color) if zone.sky_color else [],
            }
            enty_bytes = msgpack.packb(enty_payload, use_bin_type=True)
            _write_chunk(f, CHUNK_ENTY, enty_bytes)

    except OSError as exc:
        raise ZoneIOError(f"Failed to write {filepath}: {exc}") from exc


# ═══════════════════════════════════════════════════════════════════
#  load_binary_zone
# ═══════════════════════════════════════════════════════════════════

def load_binary_zone(
    filepath: str | Path,
    sim_only: bool = False,
) -> dict[str, Any]:
    """Read a binary ``.zone`` file and return its contents as a dict.

    Parameters
    ----------
    filepath : str | Path
        Path to the ``.zone`` file.
    sim_only : bool
        If ``True``, the **RNDR** chunk is skipped to save memory.
        The returned dict will not contain ``"textures"`` or
        ``"light_levels"`` keys.

    Returns
    -------
    dict
        Keys present in all modes:

        * ``"width"``  — ``int``
        * ``"height"`` — ``int``
        * ``"navi_grid"``    — ``np.ndarray  uint16  [H, W]``
        * ``"floor_z"``      — ``np.ndarray  float32 [H, W]``
        * ``"ceil_z"``       — ``np.ndarray  float32 [H, W]``
        * ``"entities"``     — ``list[dict]``
        * ``"portals"``      — ``list[dict]``
        * ``"overlay_walls"`` — ``list[dict]``
        * ``"name"``         — ``str``
        * ``"first_person"`` — ``bool``
        * ``"anchor"``       — ``list[float]``

        Additional keys when *sim_only* is ``False``:

        * ``"textures"``     — ``np.ndarray  uint16  [H, W, 6]``
        * ``"light_levels"`` — ``np.ndarray  float32 [H, W]``

    Raises
    ------
    ZoneIOError
        On any validation or I/O error.
    """
    filepath = Path(filepath)

    try:
        with open(filepath, "rb") as f:
            # ── Global header ─────────────────────────────────────
            hdr_raw = f.read(HEADER_SIZE)
            if len(hdr_raw) < HEADER_SIZE:
                raise ZoneIOError(
                    f"File too short for header ({len(hdr_raw)} B): {filepath}")

            magic, version, _flags, W, H = struct.unpack(HEADER_FMT, hdr_raw)

            if magic != ZONE_MAGIC:
                raise ZoneIOError(
                    f"Bad magic 0x{magic:08X} (expected 0x{ZONE_MAGIC:08X}): "
                    f"{filepath}")
            if version > ZONE_VERSION:
                raise ZoneIOError(
                    f"Unsupported version {version} (max {ZONE_VERSION}): "
                    f"{filepath}")

            cells = H * W

            # ── Result accumulator ────────────────────────────────
            result: dict[str, Any] = {
                "width": W,
                "height": H,
            }

            # ── Chunk reader loop ─────────────────────────────────
            while True:
                chunk_hdr = f.read(CHUNK_HEADER_SIZE)
                if len(chunk_hdr) == 0:
                    break  # EOF — done
                if len(chunk_hdr) < CHUNK_HEADER_SIZE:
                    raise ZoneIOError(
                        f"Truncated chunk header ({len(chunk_hdr)} B): "
                        f"{filepath}")

                chunk_id, chunk_len = struct.unpack(
                    CHUNK_HEADER_FMT, chunk_hdr)

                # -- NAVI -------------------------------------------
                if chunk_id == CHUNK_NAVI:
                    expected = cells * np.dtype(np.uint16).itemsize
                    if chunk_len != expected:
                        raise ZoneIOError(
                            f"NAVI chunk size mismatch: got {chunk_len}, "
                            f"expected {expected}")
                    raw = f.read(chunk_len)
                    result["navi_grid"] = np.frombuffer(
                        raw, dtype=np.uint16).reshape((H, W)).copy()

                # -- ELEV -------------------------------------------
                elif chunk_id == CHUNK_ELEV:
                    f32_size = np.dtype(np.float32).itemsize
                    expected = cells * f32_size * 2  # floor + ceil
                    if chunk_len != expected:
                        raise ZoneIOError(
                            f"ELEV chunk size mismatch: got {chunk_len}, "
                            f"expected {expected}")
                    raw = f.read(chunk_len)
                    half = cells * f32_size
                    result["floor_z"] = np.frombuffer(
                        raw[:half], dtype=np.float32).reshape((H, W)).copy()
                    result["ceil_z"] = np.frombuffer(
                        raw[half:], dtype=np.float32).reshape((H, W)).copy()

                # -- RNDR -------------------------------------------
                elif chunk_id == CHUNK_RNDR:
                    if sim_only:
                        f.seek(chunk_len, 1)
                        continue
                    u16_size = np.dtype(np.uint16).itemsize
                    f32_size = np.dtype(np.float32).itemsize
                    tex_bytes = cells * 6 * u16_size
                    light_bytes = cells * f32_size
                    expected = tex_bytes + light_bytes
                    if chunk_len != expected:
                        raise ZoneIOError(
                            f"RNDR chunk size mismatch: got {chunk_len}, "
                            f"expected {expected}")
                    raw = f.read(chunk_len)
                    result["textures"] = np.frombuffer(
                        raw[:tex_bytes], dtype=np.uint16
                    ).reshape((H, W, 6)).copy()
                    result["light_levels"] = np.frombuffer(
                        raw[tex_bytes:], dtype=np.float32
                    ).reshape((H, W)).copy()

                # -- ENTY -------------------------------------------
                elif chunk_id == CHUNK_ENTY:
                    raw = f.read(chunk_len)
                    enty = msgpack.unpackb(raw, raw=False)
                    result["entities"] = enty.get("entities", [])
                    result["portals"] = enty.get("portals", [])
                    result["overlay_walls"] = enty.get("overlay_walls", [])
                    result["name"] = enty.get("name", "")
                    result["first_person"] = enty.get("first_person", False)
                    result["anchor"] = enty.get("anchor", [0.0, 0.0])
                    # Raw editor grids
                    result["tiles"] = enty.get("tiles", [])
                    result["rotations"] = enty.get("rotations", [])
                    result["floor_textures"] = enty.get("floor_textures", [])
                    result["ceil_textures"] = enty.get("ceil_textures", [])
                    result["wall_textures"] = enty.get("wall_textures", [])
                    result["face_textures"] = enty.get("face_textures", [])
                    result["_light_levels_raw"] = enty.get("light_levels", [])
                    result["wall_segments"] = enty.get("wall_segments", [])
                    result["floor_step_textures"] = enty.get("floor_step_textures", [])
                    result["ceil_step_textures"] = enty.get("ceil_step_textures", [])
                    result["floor_step_segments"] = enty.get("floor_step_segments", [])
                    result["ceil_step_segments"] = enty.get("ceil_step_segments", [])
                    result["upper_wall_height"] = enty.get("upper_wall_height", [])
                    result["boxes"] = enty.get("boxes", [])
                    result["quads"] = enty.get("quads", [])
                    result["reflect_map"] = enty.get("reflect_map", [])
                    result["curves"] = enty.get("curves", [])
                    result["floor_slope_dx"] = enty.get("floor_slope_dx", [])
                    result["floor_slope_dy"] = enty.get("floor_slope_dy", [])
                    result["floor2_heights"] = enty.get("floor2_heights", [])
                    result["ceil2_heights"] = enty.get("ceil2_heights", [])
                    result["floor2_textures"] = enty.get("floor2_textures", [])
                    result["ceil2_textures"] = enty.get("ceil2_textures", [])
                    result["upper_wall_height2"] = enty.get("upper_wall_height2", [])
                    result["fog_density"] = enty.get("fog_density", [])
                    result["fog_color"] = enty.get("fog_color", [])
                    result["render_portals"] = enty.get("render_portals", [])
                    result["skybox"] = enty.get("skybox", "")
                    result["sky_color"] = tuple(enty.get("sky_color", []))

                # -- Unknown chunk — skip ---------------------------
                else:
                    f.seek(chunk_len, 1)

            # ── Validate required chunks ──────────────────────────
            for key in ("navi_grid", "floor_z", "ceil_z"):
                if key not in result:
                    raise ZoneIOError(
                        f"Missing required chunk data '{key}': {filepath}")

            # Default ENTY fields if chunk was absent
            result.setdefault("entities", [])
            result.setdefault("portals", [])
            result.setdefault("overlay_walls", [])
            result.setdefault("name", filepath.stem)
            result.setdefault("first_person", False)
            result.setdefault("anchor", [0.0, 0.0])
            result.setdefault("tiles", [])
            result.setdefault("rotations", [])
            result.setdefault("floor_textures", [])
            result.setdefault("ceil_textures", [])
            result.setdefault("wall_textures", [])
            result.setdefault("face_textures", [])
            result.setdefault("_light_levels_raw", [])
            result.setdefault("wall_segments", [])
            result.setdefault("floor_step_textures", [])
            result.setdefault("ceil_step_textures", [])
            result.setdefault("floor_step_segments", [])
            result.setdefault("ceil_step_segments", [])
            result.setdefault("upper_wall_height", [])
            result.setdefault("boxes", [])
            result.setdefault("quads", [])
            result.setdefault("reflect_map", [])
            result.setdefault("curves", [])
            result.setdefault("floor_slope_dx", [])
            result.setdefault("floor_slope_dy", [])
            result.setdefault("floor_slope_div", [])
            result.setdefault("floor2_heights", [])
            result.setdefault("ceil2_heights", [])
            result.setdefault("floor2_textures", [])
            result.setdefault("ceil2_textures", [])
            result.setdefault("upper_wall_height2", [])
            result.setdefault("fog_density", [])
            result.setdefault("fog_color", [])
            result.setdefault("render_portals", [])
            result.setdefault("skybox", "")
            result.setdefault("sky_color", ())

            return result

    except OSError as exc:
        raise ZoneIOError(f"Failed to read {filepath}: {exc}") from exc
