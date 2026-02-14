"""
main.py — Bootstrap

1. Create the app
2. Load game data (items, loot tables)
3. Resolve starting zone
4. Create the player (restoring from save if present)
5. Spawn NPCs / containers
6. Push the starting scene
7. Run
"""

from core.app import App
from core.bootstrap import (
    load_game_data, resolve_zone, create_player,
    setup_world_resources, spawn_characters,
)
from scenes.world_scene import WorldScene


def main():
    app = App(title="Shopkeeper", width=960, height=640)

    load_game_data(app)

    tiles, default_zone, editor_mode = resolve_zone()

    player, start_zone = create_player(app, default_zone, editor_mode)

    setup_world_resources(app, tiles, default_zone)

    spawn_characters(app)

    app.push_scene(WorldScene(editor_mode=editor_mode, zone_name=start_zone))
    app.run()


if __name__ == "__main__":
    main()