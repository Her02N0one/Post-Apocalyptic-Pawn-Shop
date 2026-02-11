"""logic/dialogue.py — Dialogue tree registry and helpers.

Dialogue trees are plain dicts stored in a DialogueManager resource.
Each tree has named nodes; each node has ``text`` (what the NPC says)
and ``choices`` (what the player can respond with).

Node format::

    {
        "text": "Hello, stranger.",
        "choices": [
            {"label": "Hi.",   "next": "greet_2"},
            {"label": "Bye.",  "action": "close"},
        ]
    }

Choice fields:
    label     — display text
    next      — node id to advance to (omit for terminal / action-only)
    action    — string command: "close", "open_trade",
                "set_flag:key", "set_flag:key:value"
    condition — "flag_name" or "!flag_name"; hides choice if unmet
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class DialogueManager:
    """World resource holding all dialogue trees."""
    _trees: dict[str, dict] = field(default_factory=dict)

    def register(self, tree_id: str, tree: dict):
        self._trees[tree_id] = tree

    def get_tree(self, tree_id: str) -> dict | None:
        return self._trees.get(tree_id)

    def get_node(self, tree_id: str, node_id: str) -> dict | None:
        tree = self._trees.get(tree_id)
        if tree:
            return tree.get(node_id)
        return None


# ── Built-in dialogue trees ─────────────────────────────────────────

BUILTIN_TREES: dict[str, dict] = {
    "trader_intro": {
        "root": {
            "text": "Hey, stranger. You look like you've seen some things.\nI've got supplies if you've got something worth trading.",
            "choices": [
                {"label": "Show me what you've got.", "action": "open_trade"},
                {"label": "What is this place?", "next": "about"},
                {"label": "Who are you?", "next": "who"},
                {"label": "I should go.", "action": "close"},
            ],
        },
        "about": {
            "text": "Used to be a gas station. Now it's the only shop\nfor miles. Everything's got a price out here.",
            "choices": [
                {"label": "Let me see your stock.", "action": "open_trade"},
                {"label": "Good to know.", "next": "root"},
            ],
        },
        "who": {
            "text": "Name's Dusty. That's all you need to know.\nI trade fair. Don't make trouble and we'll get along.",
            "choices": [
                {"label": "Fair enough. Let's trade.", "action": "open_trade"},
                {"label": "Right.", "next": "root"},
            ],
        },
    },
    "settler_generic": {
        "root": {
            "text": "Stay safe out there. Raiders have been getting\nbolder lately.",
            "choices": [
                {"label": "I can handle myself.", "next": "tough"},
                {"label": "Thanks for the warning.", "action": "close"},
            ],
        },
        "tough": {
            "text": "That's what the last guy said. Didn't end well for him.",
            "choices": [
                {"label": "I'll be careful.", "action": "close"},
            ],
        },
    },
}


def load_builtin_trees(manager: DialogueManager):
    """Register all built-in dialogue trees."""
    for tree_id, tree in BUILTIN_TREES.items():
        manager.register(tree_id, tree)
