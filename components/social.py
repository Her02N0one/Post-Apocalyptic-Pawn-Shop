"""components.social — Faction allegiance, dialogue, and crime tracking."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Faction:
    """Which group this entity belongs to and its stance toward the player.

    ``group`` identifies the faction (e.g. "raiders", "settlers", "player").
    ``disposition`` is the *current* stance: "friendly", "neutral", or "hostile".
    ``home_disposition`` is the default stance — entities revert to this
    after combat disengagement (leash return, etc.).
    ``alert_radius`` controls how far the aggro-propagation reaches when this
    entity is attacked.
    """
    group: str = "neutral"
    disposition: str = "neutral"        # friendly | neutral | hostile
    home_disposition: str = "neutral"   # what to revert to when calm
    alert_radius: float = 12.0         # tiles — allies within this go hostile


@dataclass
class Dialogue:
    """Marks an entity as talkable and references its dialogue tree.

    ``tree_id`` is the key into DialogueManager's tree registry.
    ``greeting`` is a shortcut for NPCs with a single line (no tree needed).
    ``bark`` is an ambient line shown when walking near (future use).
    ``can_trade`` opens the transfer modal after dialogue concludes.
    """
    tree_id: str = ""
    greeting: str = ""
    bark: str = ""
    can_trade: bool = False


@dataclass
class Ownership:
    """Marks a container or item as owned by a faction.

    ``faction_group`` is the group that owns this (e.g. "settlers").
    Taking from an owned container is theft — witnesses will report it.
    """
    faction_group: str = "settlers"


@dataclass
class CrimeRecord:
    """Tracks crimes the player has committed against each faction.

    ``offenses`` maps faction group → count of witnessed crimes.
    ``total_witnessed`` is how many crimes were witnessed overall.
    ``decay_timer`` tracks time since last crime for reputation decay.

    This component lives on the player entity.  NPCs learn about crimes
    through witness memories (WorldMemory ``crime:`` prefix) that
    spread via word-of-mouth when friendlies share information at
    subzone checkpoints.
    """
    offenses: dict[str, int] = field(default_factory=dict)
    total_witnessed: int = 0
    decay_timer: float = 0.0   # game-minutes since last crime

    def record(self, faction_group: str) -> None:
        self.offenses[faction_group] = self.offenses.get(faction_group, 0) + 1
        self.total_witnessed += 1
        self.decay_timer = 0.0

    def severity(self, faction_group: str) -> int:
        """Return how many witnessed crimes against a faction."""
        return self.offenses.get(faction_group, 0)


@dataclass
class Locked:
    """Container or door that requires faction access or lockpicking.

    Settlers secure their storehouses with locks rather than posting
    guards at every door.  Members of ``faction_access`` open freely;
    everyone else must pick the lock (a crime if witnessed).

    ``difficulty`` affects lockpick success chance:
        0 = trivial (always succeeds)
        1 = easy    (~75 %)
        2 = medium  (~50 %)
        3 = hard    (~25 %)
    """
    faction_access: str = "settlers"
    difficulty: int = 1
