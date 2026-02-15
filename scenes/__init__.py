"""scenes — Game screen states.

Submodules
----------
world/          The main gameplay scene (scene, draw, update, zones, editor)
debug_scene     Debug overlay scene
gym_scene       Combat testing scene
zoo_scene       Entity showcase scene
museum_scene    Exhibit-based testing scene
scene_picker    Scene selection menu

exhibits/       Isolated test exhibits for the museum scene
"""

__all__ = [
    "world", "debug_scene",
    "gym_scene", "zoo_scene", "museum_scene",
    "scene_picker",
]
