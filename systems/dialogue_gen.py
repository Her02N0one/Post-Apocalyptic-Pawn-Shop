"""systems/dialogue_gen.py — Generate contextual NPC dialogue trees.

Reads the NPC's health, zone, time-of-day, and recent world events
to build a dialogue tree that the existing ``DialogueModal`` can display.

Usage::

    from systems.dialogue_gen import build_npc_dialogue
    tree = build_npc_dialogue(world, npc_eid)
    modal = DialogueModal(tree, npc_name="Old Pete", npc_eid=npc_eid)
"""

from __future__ import annotations

import random
from typing import Any, TYPE_CHECKING

from components import (
    Identity, Health, Position, Sprite,
    WorldClock, WorldEventLog, GameClock,
)
from core.types import EntityKind

if TYPE_CHECKING:
    from core.ecs import World


# ── Line generators ───────────────────────────────────────────────────

def _time_greeting(wc: "WorldClock | None") -> str:
    if wc is None:
        return "Hey there."
    phase = wc.day_phase
    if 0.25 <= phase < 0.50:
        return random.choice(["Good morning.", "Morning!", "Nice day so far."])
    elif 0.50 <= phase < 0.75:
        return random.choice(["Good afternoon.", "Hey.", "Hot day, isn't it?"])
    elif 0.75 <= phase < 0.90:
        return random.choice(["Evening.", "Getting dark soon.", "What a day."])
    else:
        return random.choice(["Shouldn't be out at night.", "Can't sleep either?",
                              "Careful after dark."])


def _health_line(hp: "Health | None") -> str | None:
    if hp is None:
        return None
    ratio = hp.current / hp.maximum if hp.maximum > 0 else 1.0
    if ratio < 0.3:
        return random.choice([
            "I'm in bad shape... need bandages.",
            "Everything hurts. Got anything to patch me up?",
            "I barely survived that fight.",
        ])
    elif ratio < 0.6:
        return random.choice([
            "I've been better. Took some hits recently.",
            "Could use some rest, to be honest.",
        ])
    return None


def _zone_line(zone: str) -> str | None:
    comments = {
        "playground": "This area feels relatively safe... for now.",
        "pawn_shop": "Looking to trade? Check the containers around here.",
        "house_interior": "Cozy enough, if you ignore the smell.",
        "outskirts": "Watch yourself — beasts roam the outskirts.",
        "crossroads": "Lot of travelers pass through the crossroads.",
        "campsite": "The campsite's got supplies, but it attracts trouble.",
    }
    return comments.get(zone)


def _event_line(event_log: "WorldEventLog | None", now: float) -> str | None:
    """Comment on a recent event."""
    if event_log is None:
        return None
    for entry in reversed(event_log.entries):
        if now - entry.time > 60:
            break
        if entry.category == "combat" and "killed" in entry.message:
            return random.choice([
                f"Did you hear? {entry.message}",
                "There's been fighting nearby. Be careful.",
                "Dangerous times... someone got hurt out there.",
            ])
        if entry.category == "combat" and "appeared" in entry.message:
            return random.choice([
                "I heard something dangerous showed up nearby.",
                "Stay alert — creatures have been spotted.",
            ])
    return None


FILLER_LINES = [
    "Not much to say right now.",
    "Stay safe out there.",
    "Things could be worse, I suppose.",
    "Have you checked the containers around here?",
    "The world's gone sideways, but we keep going.",
    "I wonder what's in the other zones right now...",
]


# ── Tree builder ──────────────────────────────────────────────────────

def build_npc_dialogue(world: "World", npc_eid: int) -> dict[str, Any]:
    """Build a dialogue tree dict for the existing DialogueModal.

    Returns a tree with a 'root' node containing contextual NPC text
    and follow-up choices that reveal more info.
    """
    wc = world.resources.try_get(WorldClock)
    gc = world.resources.try_get(GameClock)
    event_log = world.resources.try_get(WorldEventLog)
    now = gc.time if gc else 0.0

    greeting = _time_greeting(wc)
    hp = world.get(npc_eid, Health)
    pos = world.get(npc_eid, Position)
    zone = pos.zone if pos else ""

    # Build main text
    main_lines = [greeting]
    health_line = _health_line(hp)
    if health_line:
        main_lines.append(health_line)

    zone_line = _zone_line(zone)
    event_line = _event_line(event_log, now)

    # Build root node text
    root_text = "\n".join(main_lines)

    # Build choices
    choices: list[dict[str, str]] = []

    if zone_line:
        choices.append({
            "label": "Tell me about this place.",
            "next": "zone_info",
        })

    if event_line:
        choices.append({
            "label": "Heard any news?",
            "next": "news",
        })

    if hp and hp.current < hp.maximum:
        choices.append({
            "label": "How are you holding up?",
            "next": "health",
        })

    choices.append({
        "label": "[Leave]",
        "action": "close",
    })

    tree: dict[str, Any] = {
        "root": {
            "text": root_text,
            "choices": choices,
        },
    }

    # Add follow-up nodes
    if zone_line:
        tree["zone_info"] = {
            "text": zone_line,
            "choices": [{"label": "I see. Thanks.", "action": "close"}],
        }

    if event_line:
        tree["news"] = {
            "text": event_line,
            "choices": [{"label": "Good to know.", "action": "close"}],
        }

    if hp and hp.current < hp.maximum:
        ratio = hp.current / hp.maximum if hp.maximum > 0 else 1.0
        if ratio < 0.3:
            health_text = "I'm barely hanging on. If you have any bandages, I'd be grateful."
        elif ratio < 0.6:
            health_text = "I've taken some hits but I'll pull through."
        else:
            health_text = "I'm alright. Nothing I can't handle."
        tree["health"] = {
            "text": health_text,
            "choices": [{"label": "Stay strong.", "action": "close"}],
        }

    return tree
