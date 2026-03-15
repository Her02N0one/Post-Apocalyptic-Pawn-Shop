#!/usr/bin/env python3
"""Quick-launch into pawn_shop to visually verify the vending machine prism.

Run:  python test_vending.py

Spawns the player near the vending machine at (8.5, 6.5).
Look around — you should see a textured box with distinct colours:
  • Front (north-facing, blue)  — "vending_front"
  • Back  (south-facing, grey)  — "vending_back"
  • Sides (east/west, muted)    — "vending_side"
  • Top   (dark cap)            — "vending_top"

Controls: WASD + mouse look (standard FPS).
Press ESC to quit.
"""

from core.app import App
from core.session import Session
from scenes.world import FirstPerson


def main() -> None:
    app = App(title="Vending Machine Test", width=960, height=640)

    session = Session(app.world)
    # Start a new game directly in pawn_shop (interior → first-person)
    session.new_game("pawn_shop")

    # Override player position to be near the vending machine
    from components import Position
    for eid, pos in app.world.query(Position):
        # The player entity will have a Player component
        if app.world.has(eid, __import__("components").Player):
            pos.x = 7.5
            pos.y = 6.5
            print(f"[TEST] Player moved to ({pos.x}, {pos.y}) — "
                  f"face east to see the vending machine at (8.5, 6.5)")
            break

    app.push_scene(FirstPerson(session))
    app.run()


if __name__ == "__main__":
    main()
