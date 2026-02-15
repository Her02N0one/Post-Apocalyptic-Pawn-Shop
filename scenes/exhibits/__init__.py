"""scenes/exhibits — Museum exhibit modules.

Each exhibit is a self-contained class that owns its setup, update,
draw, and teardown logic.  MuseumScene acts as a thin tab-bar host
that delegates to the active exhibit.

See ``base.py`` for the Exhibit protocol.
"""

from scenes.exhibits.base import Exhibit
from scenes.exhibits.patrol_exhibit import PatrolExhibit
from scenes.exhibits.combat_exhibit import CombatExhibit
from scenes.exhibits.hearing_exhibit import HearingExhibit
from scenes.exhibits.pathfinding_exhibit import PathfindingExhibit
from scenes.exhibits.faction_exhibit import FactionExhibit
from scenes.exhibits.vision_exhibit import VisionExhibit
from scenes.exhibits.particle_exhibit import ParticleExhibit
from scenes.exhibits.needs_exhibit import NeedsExhibit
from scenes.exhibits.lod_exhibit import LODExhibit
from scenes.exhibits.stat_combat_exhibit import StatCombatExhibit
from scenes.exhibits.economy_exhibit import EconomyExhibit
from scenes.exhibits.crime_exhibit import CrimeExhibit
