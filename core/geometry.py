"""core/geometry.py — Pure-math geometry helpers.

Zero ECS / component imports.  Every helper is a tiny, stateless function
that operates on floats or tuples so the rest of the codebase can share
a single source of truth for spatial math.

All angles are in **radians** unless otherwise noted.
"""

from __future__ import annotations
import math

__all__ = [
    "dist",
    "normalize",
    "facing_to_angle",
    "angle_to_facing",
    "direction_from_delta",
    "angle_diff",
]


# ── Distance ────────────────────────────────────────────────────────

def dist(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance between two points."""
    return math.hypot(bx - ax, by - ay)


# ── Vector normalisation ────────────────────────────────────────────

def normalize(dx: float, dy: float) -> tuple[float, float]:
    """Return unit-length (nx, ny).  Returns (0, 0) for zero-length input."""
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return (0.0, 0.0)
    return (dx / d, dy / d)


# ── Facing ↔ angle conversion ───────────────────────────────────────

_FACING_ANGLES: dict[str, float] = {
    "right": 0.0,
    "down":  math.pi / 2,
    "left":  math.pi,
    "up":    -math.pi / 2,
}


def facing_to_angle(direction: str) -> float:
    """Convert a cardinal Facing.direction string to radians.

    right → 0, down → π/2, left → π, up → −π/2
    """
    return _FACING_ANGLES.get(direction, 0.0)


def angle_to_facing(angle: float) -> str:
    """Convert a radian angle to the nearest cardinal direction string.

    This is the inverse of :func:`facing_to_angle`.
    """
    deg = math.degrees(angle) % 360
    if 45 <= deg < 135:
        return "down"
    elif 135 <= deg < 225:
        return "left"
    elif 225 <= deg < 315:
        return "up"
    return "right"


def direction_from_delta(dx: float, dy: float) -> str:
    """Choose the cardinal direction that best matches a delta vector.

    Uses the dominant-axis heuristic: if |dx| >= |dy|, the result is
    horizontal; otherwise vertical.  Returns ``"down"`` for a zero vector.
    """
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return "down"
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


# ── Angle helpers ────────────────────────────────────────────────────

def angle_diff(a: float, b: float) -> float:
    """Signed shortest angular distance from *a* to *b* in radians.

    Result is in (−π, π].
    """
    return math.atan2(math.sin(b - a), math.cos(b - a))
