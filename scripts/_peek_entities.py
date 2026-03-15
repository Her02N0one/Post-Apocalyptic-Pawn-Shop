"""Peek at entity descriptors in all zone files."""
import struct, msgpack, json, sys
from pathlib import Path

# Add project root to path so we can import the format constants
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.zones.format import (
    ZONE_MAGIC, HEADER_FMT, HEADER_SIZE,
    CHUNK_HEADER_FMT, CHUNK_HEADER_SIZE, CHUNK_ENTY,
)

zones_dir = Path(__file__).resolve().parent.parent / "zones"
print(f"Looking in: {zones_dir}")

for zf in sorted(zones_dir.glob("*.zone")):
    with open(zf, "rb") as f:
        hdr = f.read(HEADER_SIZE)
        magic, ver, flags, W, H = struct.unpack(HEADER_FMT, hdr)
        if magic != ZONE_MAGIC:
            print(f"  {zf.name}: bad magic 0x{magic:08X}")
            continue
        while True:
            ch = f.read(CHUNK_HEADER_SIZE)
            if not ch:
                break
            cid, clen = struct.unpack(CHUNK_HEADER_FMT, ch)
            if cid == CHUNK_ENTY:
                raw = f.read(clen)
                data = msgpack.unpackb(raw, raw=False)
                ents = data.get("entities", [])
                print(f"\n=== {zf.name} ({W}x{H}): {len(ents)} entities ===")
                for e in ents[:3]:
                    print(f"  {json.dumps(e, default=str)}")
                if len(ents) > 3:
                    print(f"  ... and {len(ents) - 3} more")
                break
            else:
                f.seek(clen, 1)
