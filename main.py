"""main.py — Bootstrap.

1. Create the app
2. Create a Session and start a new game
3. Push the scene (presentation only — reads from session)
4. Run
"""

from core.app import App
from core.session import Session
from scenes.world import WorldScene

START_ZONE = "playground"


def main():
    app = App(title="Shopkeeper", width=960, height=640)

    # Session owns the data pipeline (zone loading, entity spawning, save/load)
    session = Session(app.world)
    session.new_game(START_ZONE)

    # Scene is presentation only — reads tiles/entities from session
    app.push_scene(WorldScene(session))
    app.run()


if __name__ == "__main__":
    main()