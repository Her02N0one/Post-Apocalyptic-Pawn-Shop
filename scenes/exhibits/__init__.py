"""scenes/exhibits — Museum exhibit modules.

Each exhibit is a self-contained class that owns its setup, update,
draw, and teardown logic.  MuseumScene acts as a thin tab-bar host
that delegates to the active exhibit.

See ``base.py`` for the Exhibit protocol.
"""

from scenes.exhibits.base import Exhibit
from scenes.exhibits.ai_exhibit import AIExhibit
from scenes.exhibits.combat_exhibit import CombatExhibit
from scenes.exhibits.lod_exhibit import LODExhibit
from scenes.exhibits.pathfinding_exhibit import PathfindingExhibit
from scenes.exhibits.faction_exhibit import FactionExhibit
from scenes.exhibits.stealth_exhibit import StealthExhibit
from scenes.exhibits.particle_exhibit import ParticleExhibit
from scenes.exhibits.needs_exhibit import NeedsExhibit
