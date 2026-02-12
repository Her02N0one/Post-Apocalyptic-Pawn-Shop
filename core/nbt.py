"""core/nbt.py — Optional NBT export helpers for zone files.

Uses `nbtlib` when available to write a simple NBT structure containing
zone tiles and metadata. When `nbtlib` isn't installed, we fall back to a
minimal custom binary format with a .nbt extension so older Pythons can
still read/write zone files without extra dependencies.
"""
from __future__ import annotations
from pathlib import Path
import struct

try:
    import nbtlib
    from nbtlib import tag
except Exception:
    nbtlib = None

NBTLIB_AVAILABLE = nbtlib is not None

_MAGIC = b"PAPSZON\x00"
_VERSION = 1


def save_zone_nbt(name: str, tiles: list[list[int]], anchor: tuple[float, float] | None = None, teleporters: dict[tuple[int,int], str] | None = None, dir_path: Path | None = None):
    """Save a minimal NBT representation of the zone.

    Structure (TAG_Compound):
      - name: TAG_String
      - width: TAG_Int
      - height: TAG_Int
      - tiles: TAG_Byte_Array (row-major)
      - anchors: TAG_List of TAG_Double (x,y)
      - teleporters: TAG_List of TAG_Compound { r:TAG_Int, c:TAG_Int, target:TAG_String }
    """
    if dir_path is None:
        dir_path = Path("zones")
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)

    if nbtlib is None:
        out_path = dir_path / f"{name}.nbt"
        with open(out_path, "wb") as f:
            f.write(_MAGIC)
            f.write(struct.pack("<B", _VERSION))
            h = len(tiles)
            w = len(tiles[0]) if h else 0
            f.write(struct.pack("<II", w, h))
            flags = 0
            if anchor:
                flags |= 0x01
            if teleporters:
                flags |= 0x02
            f.write(struct.pack("<B", flags))
            if anchor:
                f.write(struct.pack("<dd", float(anchor[0]), float(anchor[1])))
            # Tiles as raw bytes (row-major)
            for row in tiles:
                for v in row:
                    f.write(struct.pack("<B", int(v) & 0xFF))
            # Teleporters
            tel_items = list(teleporters.items()) if teleporters else []
            f.write(struct.pack("<I", len(tel_items)))
            for (r, c), target in tel_items:
                f.write(struct.pack("<ii", int(r), int(c)))
                if isinstance(target, str):
                    zone = target
                    f.write(struct.pack("<B", 0))
                elif isinstance(target, dict):
                    zone = str(target.get("zone", ""))
                    f.write(struct.pack("<B", 1))
                else:
                    zone = str(target)
                    f.write(struct.pack("<B", 0))
                zone_bytes = zone.encode("utf-8")
                f.write(struct.pack("<H", len(zone_bytes)))
                f.write(zone_bytes)
                if isinstance(target, dict) and "r" in target and "c" in target:
                    f.write(struct.pack("<ii", int(target["r"]), int(target["c"])))
        return out_path

    h = len(tiles)
    w = len(tiles[0]) if h else 0
    # Flatten tiles into a single byte array (row-major). Use ints mod 256.
    flat = bytearray()
    for row in tiles:
        for v in row:
            flat.append(int(v) & 0xFF)

    root = nbtlib.Compound()
    root["name"] = tag.String(name)
    root["width"] = tag.Int(w)
    root["height"] = tag.Int(h)
    root["tiles"] = tag.ByteArray(flat)
    if anchor:
        root["anchor_x"] = tag.Double(float(anchor[0]))
        root["anchor_y"] = tag.Double(float(anchor[1]))
    if teleporters:
        tel_list = nbtlib.List[nbtlib.Compound]()
        for (r, c), target in teleporters.items():
            comp = nbtlib.Compound()
            comp["r"] = tag.Int(int(r))
            comp["c"] = tag.Int(int(c))
            # target may be a plain zone string or a dict with explicit coords
            if isinstance(target, (str,)):
                comp["target_zone"] = tag.String(str(target))
            elif isinstance(target, dict):
                comp["target_zone"] = tag.String(str(target.get("zone", "")))
                if "r" in target and "c" in target:
                    comp["target_r"] = tag.Int(int(target["r"]))
                    comp["target_c"] = tag.Int(int(target["c"]))
            else:
                # fallback to string representation
                comp["target_zone"] = tag.String(str(target))
            tel_list.append(comp)
        root["teleporters"] = tel_list

    nbt_file = nbtlib.File(root)
    out_path = dir_path / f"{name}.nbt"
    # Remove old file if exists to ensure clean overwrite
    if out_path.exists():
        out_path.unlink()
    nbt_file.save(out_path)
    return out_path


def load_zone_nbt(path: Path):
    """Load a zone NBT file and return a dict with keys: name, tiles, anchors, teleporters, spawns.

    `spawns` is a list of spawn dictionaries (may be empty).
    """
    path = Path(path)
    if nbtlib is None:
        with open(path, "rb") as f:
            magic = f.read(len(_MAGIC))
            if magic != _MAGIC:
                raise ImportError("nbtlib is required to load NBT files")
            version = struct.unpack("<B", f.read(1))[0]
            if version != _VERSION:
                raise ValueError("Unsupported zone format version")
            w, h = struct.unpack("<II", f.read(8))
            flags = struct.unpack("<B", f.read(1))[0]
            anchors = None
            if flags & 0x01:
                ax, ay = struct.unpack("<dd", f.read(16))
                anchors = {path.stem: [float(ax), float(ay)]}
            tiles = []
            for r in range(h):
                row = [struct.unpack("<B", f.read(1))[0] for _ in range(w)]
                tiles.append(row)
            teleporters = {}
            tel_count = struct.unpack("<I", f.read(4))[0]
            for _ in range(tel_count):
                r, c = struct.unpack("<ii", f.read(8))
                ttype = struct.unpack("<B", f.read(1))[0]
                zlen = struct.unpack("<H", f.read(2))[0]
                zone = f.read(zlen).decode("utf-8")
                if ttype == 1:
                    tr, tc = struct.unpack("<ii", f.read(8))
                    teleporters[f"{r},{c}"] = {"zone": zone, "r": tr, "c": tc}
                else:
                    teleporters[f"{r},{c}"] = zone
        return {
            "name": path.stem,
            "tiles": tiles,
            "anchors": anchors,
            "teleporters": teleporters,
            "spawns": [],
        }

    f = nbtlib.load(path)
    # In nbtlib 2.0+, the File object IS the root compound
    root = f
    name = str(root.get("name") or path.stem)
    w = int(root.get("width") or 0)
    h = int(root.get("height") or 0)
    tiles = None
    if "tiles" in root:
        ba = bytes(root["tiles"])
        # reconstruct row-major 2D array
        if w > 0 and h > 0 and len(ba) >= w * h:
            tiles = []
            for r in range(h):
                row = [int(ba[r * w + c]) for c in range(w)]
                tiles.append(row)
    anchors = None
    if "anchor_x" in root and "anchor_y" in root:
        anchors = {name: [float(root["anchor_x"]), float(root["anchor_y"]) ]}
    teleporters = {}
    if "teleporters" in root:
        for comp in root["teleporters"]:
            try:
                r = int(comp.get("r"))
                c = int(comp.get("c"))
                # support legacy 'target' and new 'target_zone' + coords
                if "target_zone" in comp:
                    tz = str(comp.get("target_zone") or "")
                    if "target_r" in comp and "target_c" in comp:
                        tr = int(comp.get("target_r"))
                        tc = int(comp.get("target_c"))
                        teleporters[f"{r},{c}"] = {"zone": tz, "r": tr, "c": tc}
                    else:
                        teleporters[f"{r},{c}"] = tz
                elif "target" in comp:
                    teleporters[f"{r},{c}"] = str(comp.get("target"))
            except Exception:
                continue

    spawns = []
    if "entities" in root:
        for ent in root["entities"]:
            # Convert tag values to python primitives where possible
            d = {}
            for k, v in ent.items():
                # nbtlib tag types expose python types via int()/str()/float()
                try:
                    d[k] = v.value
                except Exception:
                    try:
                        d[k] = int(v)
                    except Exception:
                        try:
                            d[k] = str(v)
                        except Exception:
                            d[k] = None
            spawns.append(d)

    return {
        "name": name,
        "tiles": tiles,
        "anchors": anchors,
        "teleporters": teleporters,
        "spawns": spawns,
    }
