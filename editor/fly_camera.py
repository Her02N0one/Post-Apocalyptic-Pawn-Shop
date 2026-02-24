"""editor/fly_camera.py — Shared first-person camera utilities.

Shared constants and movement math used by both ``Zone3DEditor``
(3D wireframe) and ``FPPreview`` (raycaster). Avoids duplicating
the WASD+sprint+mouse-look pattern in two places.

Usage::

    from editor.fly_camera import MOUSE_SENS, KB_TURN_SPEED, wasd_2d, wasd_3d
"""

from __future__ import annotations

import math

# ── Shared constants ─────────────────────────────────────────────

MOUSE_SENS: float = 0.003
"""Radians per pixel of mouse motion (shared by both 3D modes)."""

KB_TURN_SPEED: float = 2.5
"""Radians per second for keyboard turning (arrow keys / Q-E)."""


# ── 2D ground-plane movement (FPPreview) ─────────────────────────

def wasd_2d(
    angle: float,
    forward: bool,
    backward: bool,
    strafe_left: bool,
    strafe_right: bool,
    speed: float,
    dt: float,
) -> tuple[float, float]:
    """Compute (dx, dy) for 2D ground-plane WASD movement.

    Returns the displacement vector; caller adds to (px, py).
    """
    dx = 0.0
    dy = 0.0
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    if forward:
        dx += cos_a * speed * dt
        dy += sin_a * speed * dt
    if backward:
        dx -= cos_a * speed * dt
        dy -= sin_a * speed * dt
    if strafe_left:
        dx += sin_a * speed * dt
        dy -= cos_a * speed * dt
    if strafe_right:
        dx -= sin_a * speed * dt
        dy += cos_a * speed * dt

    return dx, dy


# ── 3D free-fly movement (Zone3DEditor) ─────────────────────────

def forward_3d(yaw: float, pitch: float) -> tuple[float, float, float]:
    """Unit forward vector in the Zone3DEditor coordinate system.

    Convention:  yaw=0  → (0, 0, 1),  pitch>0 → look *up* (+Y).
    Matches ``Zone3DEditor._forward()``.
    """
    cp = math.cos(pitch)
    return (-cp * math.sin(yaw), math.sin(pitch), cp * math.cos(yaw))


def right_3d(yaw: float) -> tuple[float, float, float]:
    """Unit right vector (always horizontal)."""
    return (-math.cos(yaw), 0.0, -math.sin(yaw))


def wasd_3d(
    yaw: float,
    pitch: float,
    forward: bool,
    backward: bool,
    strafe_left: bool,
    strafe_right: bool,
    up: bool,
    down: bool,
    speed: float,
    dt: float,
) -> tuple[float, float, float]:
    """Compute (dx, dy, dz) for full 3D free-fly WASD movement.

    Y is vertical.  Returns the displacement vector; caller adds to position.
    Uses the same coordinate system as ``Zone3DEditor``.
    """
    fx, fy, fz = forward_3d(yaw, pitch)
    rx, _, rz = right_3d(yaw)

    dx, dy, dz = 0.0, 0.0, 0.0
    v = speed * dt

    if forward:
        dx += fx * v
        dy += fy * v
        dz += fz * v
    if backward:
        dx -= fx * v
        dy -= fy * v
        dz -= fz * v
    if strafe_left:
        dx -= rx * v
        dz -= rz * v
    if strafe_right:
        dx += rx * v
        dz += rz * v
    if up:
        dy += v
    if down:
        dy -= v

    return dx, dy, dz


# ── Pitch clamping helper ────────────────────────────────────────

PITCH_LIMIT: float = math.pi * 0.45


def clamp_pitch(pitch: float) -> float:
    """Clamp pitch to ±PITCH_LIMIT to prevent gimbal-lock flip."""
    return max(-PITCH_LIMIT, min(PITCH_LIMIT, pitch))
