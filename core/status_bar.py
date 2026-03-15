"""core.status_bar — HUD status / toast message state.

Extracted from ``core.session`` so HUD state is a discrete, passable
object that systems can write to and scenes can read from without
coupling to the full Session.

Usage::

    bar = StatusBar()
    bar.show("Picked up Medkit", 1.5)
    # … in scene update …
    bar.tick(dt)
    if bar.timer > 0:
        draw_text(bar.message)
"""

from __future__ import annotations


class StatusBar:
    """Tiny toast / status-message holder.

    Attributes
    ----------
    message : str
        Current text to display.
    timer : float
        Seconds remaining for the message.  When ≤ 0 the HUD hides it.
    """

    __slots__ = ("message", "timer")

    def __init__(self, message: str = "", timer: float = 0.0) -> None:
        self.message = message
        self.timer = timer

    def show(self, msg: str, duration: float = 1.5) -> None:
        """Display *msg* for *duration* seconds."""
        self.message = msg
        self.timer = duration

    def tick(self, dt: float) -> None:
        """Count down the timer.  Call from scene.update()."""
        if self.timer > 0:
            self.timer -= dt

    # Truthiness: True while a message is actively showing
    def __bool__(self) -> bool:
        return self.timer > 0 and bool(self.message)

    def __repr__(self) -> str:
        return f"StatusBar({self.message!r}, timer={self.timer:.2f})"
