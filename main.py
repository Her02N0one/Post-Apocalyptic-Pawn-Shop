"""main.py — Bootstrap.

1. Create the app
2. Spawn the player entity at the zone anchor
3. Push the starting scene
4. Run
"""

from core.app import App
from core.types import Direction, EntityKind
from core.zones import load_zone
from components import (
    Position, Velocity, Sprite, Player, Facing, Identity, Health,
    Collider, Camera,
)
from scenes.world import WorldScene

START_ZONE = "playground"


def main():
    app = App(title="Shopkeeper", width=960, height=640)

    # Load zone to get anchor point
    zone = load_zone(START_ZONE)
    ax, ay = zone.anchor

    # ── Player entity ────────────────────────────────────────────
    player = app.world.spawn()
    app.world.add(player, Position(x=ax, y=ay, zone=START_ZONE))
    app.world.add(player, Velocity())
    app.world.add(player, Sprite(char="@", color=(255, 255, 100), layer=10))
    app.world.add(player, Player(speed=6.0))
    app.world.add(player, Facing(direction=Direction.DOWN))
    app.world.add(player, Identity(name="You", kind=EntityKind.PLAYER))
    app.world.add(player, Health())
    app.world.add(player, Collider(w=0.8, h=0.8, solid=True))

    # ── World resources ──────────────────────────────────────────
    app.world.resources.set(Camera())

    # ── Go ───────────────────────────────────────────────────────
    app.push_scene(WorldScene())
    app.run()


if __name__ == "__main__":
    main()