"""Quick analysis of a perf CSV log."""
import csv, statistics, sys

path = sys.argv[1] if len(sys.argv) > 1 else "logs/perf_20260219_103816.csv"
rows = list(csv.DictReader(open(path)))
n = len(rows)
dur = float(rows[-1]["wall_clock_ms"]) / 1000
print(f"Frames: {n}  Duration: {dur:.1f}s")
print()

cols = [
    "dt_frame_total", "dt_cast", "dt_walls", "dt_blit_walls",
    "dt_floor_ceil", "dt_visplane", "dt_entities", "dt_hud",
    "dt_upscale", "dt_tint",
]
for c in cols:
    vals = [float(r[c]) for r in rows if r[c]]
    if not vals:
        continue
    med = statistics.median(vals)
    s = sorted(vals)
    p95 = s[int(len(s) * 0.95)]
    p99 = s[int(len(s) * 0.99)]
    mx = max(s)
    mn = min(s)
    print(f"  {c:20s}  med={med:6.3f}  p95={p95:6.3f}  p99={p99:6.3f}  max={mx:7.3f}  min={mn:6.3f}")

fps_vals = [float(r["fps"]) for r in rows]
print(f"\nFPS  avg={statistics.mean(fps_vals):.1f}  med={statistics.median(fps_vals):.1f}  min={min(fps_vals):.1f}  max={max(fps_vals):.1f}")

# Spike analysis
for thresh in [10, 8]:
    spikes = [(int(r["frame"]), float(r["dt_frame_total"])) for r in rows if float(r["dt_frame_total"]) > thresh]
    print(f"\nSpikes >{thresh}ms: {len(spikes)}")
    for f, t in spikes[:20]:
        r = rows[f]
        fl = float(r["dt_floor_ceil"])
        wa = float(r["dt_walls"])
        en = float(r["dt_entities"])
        hu = float(r["dt_hud"])
        print(f"  frame {f:4d}: {t:6.1f}ms  floor={fl:5.1f}  wall={wa:5.3f}  ent={en:5.3f}  hud={hu:5.3f}")

# Cache info
sc = [int(r["strip_cache_size"]) for r in rows]
scp = [int(r["strip_cache_prev_size"]) for r in rows]
print(f"\nStrip cache      min={min(sc)}  max={max(sc)}  final={sc[-1]}")
print(f"Strip cache prev min={min(scp)}  max={max(scp)}  final={scp[-1]}")

c_ext = rows[0].get("c_extension_active", "")
print(f"C extension: {c_ext}")

# Warmup analysis: first 50 frames vs rest
if n > 100:
    first50 = [float(r["dt_frame_total"]) for r in rows[:50]]
    rest = [float(r["dt_frame_total"]) for r in rows[50:]]
    print(f"\nWarmup: first 50 frames med={statistics.median(first50):.3f}ms  max={max(first50):.3f}ms")
    print(f"        remaining frames med={statistics.median(rest):.3f}ms  max={max(rest):.3f}ms")
