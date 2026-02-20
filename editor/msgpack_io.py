"""editor/msgpack_io.py — MessagePack binary zone export/import.

Implements the **Palette Pattern** binary format:

* **Header** (lightweight, ~200 bytes): zone name, dimensions,
  portal list, anchor.  Useful for world-map web tools.
* **Payload** (heavier): palette dict, flat index grid, entity list.

Both are packed into a single ``.mpz`` file:

    ┌────────────────────┐
    │ 4 bytes  header_len│  (big-endian uint32)
    │ header   (msgpack) │
    │ payload  (msgpack) │
    └────────────────────┘

Runtime can load just the header (seek past payload) for fast
world-graph queries.

Dependencies:
    pip install msgpack
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

try:
    import msgpack
except ImportError:
    msgpack = None  # type: ignore[assignment]

from editor.palette_format import zone_to_palette_dict, palette_dict_to_zone


# ── Paths ────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZONES_DIR     = _PROJECT_ROOT / "zones"


# ═════════════════════════════════════════════════════════════════════
#  Export  (zone dict → .mpz binary)
# ═════════════════════════════════════════════════════════════════════

def _ensure_msgpack():
    if msgpack is None:
        raise ImportError(
            "msgpack is not installed.  Run:  pip install msgpack")


def export_zone_msgpack(zone_data: dict[str, Any],
                        out_path: Path | str | None = None) -> bytes:
    """Convert a classic zone dict to binary MessagePack format.

    If *out_path* is given, writes the file and returns the raw bytes.
    Otherwise just returns the bytes without writing.

    Returns the full binary blob (header_len + header + payload).
    """
    _ensure_msgpack()

    # 1. Convert to palette format
    pal = zone_to_palette_dict(zone_data)

    # 2. Split into header / payload
    header: dict[str, Any] = {
        "name": pal.get("name", ""),
        "width": pal.get("width", 0),
        "height": pal.get("height", 0),
        "anchor": pal.get("anchor", [15.0, 10.0]),
        "portals": pal.get("portals", []),
        "first_person": pal.get("first_person", False),
    }

    payload: dict[str, Any] = {
        "palette": pal.get("palette", {}),
        "grid": pal.get("grid", []),
        "entities": pal.get("entities", []),
    }

    # 3. Serialise
    header_bytes = msgpack.packb(header, use_bin_type=True)
    payload_bytes = msgpack.packb(payload, use_bin_type=True)

    # 4. Combine with a 4-byte header-length prefix
    header_len = len(header_bytes)
    blob = struct.pack(">I", header_len) + header_bytes + payload_bytes

    # 5. Optionally write to disk
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(blob)

    return blob


def export_zone_file(zone_name: str) -> Path | None:
    """Export a zone from its JSON to ``.mpz`` in the same folder.

    Returns the output path on success, ``None`` on failure.
    """
    import json
    json_path = ZONES_DIR / f"{zone_name}.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        data = json.load(f)
    out = ZONES_DIR / f"{zone_name}.mpz"
    export_zone_msgpack(data, out)
    return out


# ═════════════════════════════════════════════════════════════════════
#  Import  (.mpz binary → zone dict)
# ═════════════════════════════════════════════════════════════════════

def _read_blob(source: bytes | Path | str) -> bytes:
    """Normalise input to raw bytes."""
    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            return f.read()
    return source


def import_header(source: bytes | Path | str) -> dict[str, Any]:
    """Read only the lightweight header from a ``.mpz`` blob.

    Fast — skips the heavy payload entirely.
    """
    _ensure_msgpack()
    raw = _read_blob(source)
    if len(raw) < 4:
        raise ValueError("Invalid .mpz: too short for header length")
    header_len = struct.unpack(">I", raw[:4])[0]
    header_bytes = raw[4:4 + header_len]
    return msgpack.unpackb(header_bytes, raw=False, strict_map_key=False)


def import_zone_msgpack(source: bytes | Path | str) -> dict[str, Any]:
    """Full import: read header + payload, return classic zone dict.

    The returned dict has standard keys (``tiles``, ``entities``,
    ``portals``, etc.) and can be fed directly to
    ``EditorState.load_zone_data()``.
    """
    _ensure_msgpack()
    raw = _read_blob(source)
    if len(raw) < 4:
        raise ValueError("Invalid .mpz: too short")

    header_len = struct.unpack(">I", raw[:4])[0]
    header_bytes = raw[4:4 + header_len]
    payload_bytes = raw[4 + header_len:]

    header = msgpack.unpackb(header_bytes, raw=False, strict_map_key=False)
    payload = msgpack.unpackb(payload_bytes, raw=False, strict_map_key=False)

    # Merge into palette dict then convert back
    pal_data: dict[str, Any] = {**header, **payload}
    zone = palette_dict_to_zone(pal_data)
    return zone


def import_zone_file(mpz_path: Path | str) -> dict[str, Any]:
    """Load a ``.mpz`` file and return a classic zone dict."""
    return import_zone_msgpack(mpz_path)


# ═════════════════════════════════════════════════════════════════════
#  Batch operations
# ═════════════════════════════════════════════════════════════════════

def export_all_zones() -> list[Path]:
    """Export every JSON zone to .mpz.  Returns list of output paths."""
    results: list[Path] = []
    for json_path in sorted(ZONES_DIR.glob("*.json")):
        out = export_zone_file(json_path.stem)
        if out:
            results.append(out)
    return results
