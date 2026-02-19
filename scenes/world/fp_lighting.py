"""scenes/world/fp_lighting.py — Day/night cycle and fog calculations.

Pure functions with no pygame dependency.  Imported by the renderer
and surface-drawing modules.
"""

from __future__ import annotations

import math

# ═════════════════════════════════════════════════════════════════════
#  Colour / gradient constants
# ═════════════════════════════════════════════════════════════════════

CEILING_DAY = (60, 70, 100)
CEILING_NIGHT = (10, 10, 25)
FLOOR_DAY = (50, 50, 45)
FLOOR_NIGHT = (20, 20, 18)
GRAD_BANDS = 24

# ═════════════════════════════════════════════════════════════════════
#  Fog parameters
# ═════════════════════════════════════════════════════════════════════

_FOG_RATE = 14            # base fog density
_FOG_RATE_NIGHT = 20      # denser fog at night
_FOG_LUT_SIZE = 256

_fog_lut_cache: dict[tuple[int, float], list[int]] = {}


def build_fog_lut(ambient: int, dn: float) -> list[int]:
    """Pre-compute fog brightness for 256 distance steps."""
    key = (ambient, round(dn, 2))
    lut = _fog_lut_cache.get(key)
    if lut is not None:
        return lut
    lut = [0] * _FOG_LUT_SIZE
    _exp = math.exp
    for i in range(_FOG_LUT_SIZE):
        dist = i * 0.125
        dist_norm = dist / 16.0
        fog_exp = max(40, min(ambient, int(ambient * _exp(-dist_norm * 1.8))))
        fog = int(fog_exp * (0.4 + 0.6 * dn))
        lut[i] = max(20, min(255, fog))
    if len(_fog_lut_cache) > 8:
        _fog_lut_cache.clear()
    _fog_lut_cache[key] = lut
    return lut


def compute_fog_params(dn: float) -> tuple[int, int, list[int]]:
    """Return ``(fog_rate, ambient, fog_lut)`` for the current day/night."""
    fog_rate = _FOG_RATE + int((_FOG_RATE_NIGHT - _FOG_RATE) * (1.0 - dn))
    ambient = int(200 + 55 * dn)
    fog_lut = build_fog_lut(ambient, dn)
    return fog_rate, ambient, fog_lut


# ═════════════════════════════════════════════════════════════════════
#  Colour helpers
# ═════════════════════════════════════════════════════════════════════


def lerp_color(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    """Linearly interpolate between two RGB colours."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def day_night_factor(wc) -> float:  # type: ignore[type-arg]
    """Return 0.0 (full night) … 1.0 (full day) based on WorldClock."""
    if wc is None:
        return 1.0
    p = wc.day_phase
    if 0.30 <= p < 0.70:
        return 1.0
    if p < 0.20 or p >= 0.85:
        return 0.0
    if 0.20 <= p < 0.30:
        return (p - 0.20) / 0.10
    if 0.70 <= p < 0.85:
        return 1.0 - (p - 0.70) / 0.15
    return 1.0
