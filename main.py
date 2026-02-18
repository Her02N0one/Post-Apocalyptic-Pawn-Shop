"""main.py — Bootstrap.

1. Create the app
2. Push the main menu scene
3. Run — the main menu handles new game / load / settings / quit
"""

from core.app import App
from scenes.main_menu import MainMenu


def main():
    app = App(title="Shopkeeper", width=960, height=640)
    app.push_scene(MainMenu())
    app.run()


if __name__ == "__main__":
    main()