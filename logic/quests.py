"""logic/quests.py — Quest tracking and global flags.

QuestLog is a world resource that dialogue actions and systems can
read/write.  Flags are simple key-value pairs used as dialogue
conditions and progression markers.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestLog:
    """World resource tracking quests and global state flags."""
    active: dict[str, dict] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    flags: dict[str, Any] = field(default_factory=dict)

    def set_flag(self, key: str, value: Any = True):
        self.flags[key] = value

    def get_flag(self, key: str, default: Any = None) -> Any:
        return self.flags.get(key, default)

    def has_flag(self, key: str) -> bool:
        return key in self.flags

    def start_quest(self, quest_id: str, data: dict | None = None):
        if quest_id not in self.active and quest_id not in self.completed:
            self.active[quest_id] = data or {}
            print(f"[QUEST] Started: {quest_id}")

    def complete_quest(self, quest_id: str):
        if quest_id in self.active:
            del self.active[quest_id]
            self.completed.add(quest_id)
            print(f"[QUEST] Completed: {quest_id}")
