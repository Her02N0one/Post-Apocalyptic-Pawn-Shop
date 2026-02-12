"""logic/crime.py — Witness-based crime detection and reputation.

Stealing is allowed, but if a friendly NPC sees you do it, they
remember.  Guards react with force; civilians spread the word.
Crime reputation travels NPC-to-NPC through word-of-mouth via the
WorldMemory system — a witness tells others when they meet at
subzone checkpoints.

Public API
----------
``find_witnesses``       — scan for NPCs who can see the theft
``report_theft``         — witnesses record the crime, guards react
``make_theft_callback``  — closure for TransferModal's on_steal hook
``npc_knows_crimes``     — does an NPC have crime memories about player?
``guard_crime_reaction`` — should a guard become hostile to the player?
"""

from __future__ import annotations
from typing import Any

from components import (
    Player, Position, Health, Identity, Faction, Dialogue,
    CrimeRecord,
)
from components.ai import Threat, AttackConfig, Brain
from components.simulation import WorldMemory


# ── Constants ────────────────────────────────────────────────────────

WITNESS_RADIUS: float = 8.0     # tiles — how far NPCs can see theft
CRIME_MEMORY_TTL: float = 1200.0  # 20 game-hours before memory fades


# ── Witness detection ────────────────────────────────────────────────

def find_witnesses(world: Any, zone: str, thief_x: float,
                   thief_y: float, radius: float = WITNESS_RADIUS
                   ) -> list[int]:
    """Find living friendly/neutral NPCs within radius of the theft.

    Returns list of witness entity IDs.  Hostile NPCs don't report
    crimes — they'd steal too.  Dead NPCs don't see anything.
    """
    witnesses: list[int] = []

    for eid, pos in world.all_of(Position):
        if pos.zone != zone:
            continue
        if world.has(eid, Player):
            continue

        # Must be alive
        health = world.get(eid, Health)
        if health and health.current <= 0:
            continue

        # Must be non-hostile (hostile mobs don't report theft)
        faction = world.get(eid, Faction)
        if faction and faction.disposition == "hostile":
            continue

        # Distance check
        dx = pos.x - thief_x
        dy = pos.y - thief_y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= radius:
            witnesses.append(eid)

    return witnesses


# ── Crime reporting ──────────────────────────────────────────────────

def report_theft(world: Any, witnesses: list[int], item_id: str,
                 owner_faction: str, game_time: float) -> str:
    """Witnesses record the crime.  Guards react with hostility.

    Updates the player's CrimeRecord and stores crime memories on
    each witness NPC.  Returns a status message for the UI flash.

    Guard identification: any NPC with an AttackConfig component
    (capable of ranged/melee combat) in a friendly faction is
    treated as a guard.
    """
    if not witnesses:
        return ""

    # Update player's crime record
    player_res = None
    for eid, _ in world.all_of(Player):
        player_res = eid
        break

    if player_res is not None:
        cr = world.get(player_res, CrimeRecord)
        if cr is None:
            cr = CrimeRecord()
            world.add(player_res, cr)
        cr.record(owner_faction)

    player_eid = player_res if player_res is not None else None

    armed_saw = False
    witness_names: list[str] = []

    for weid in witnesses:
        ident = world.get(weid, Identity)
        wname = ident.name if ident else "someone"
        witness_names.append(wname)

        # Store crime memory on the witness
        wmem = world.get(weid, WorldMemory)
        if wmem is None:
            wmem = WorldMemory()
            world.add(weid, wmem)
        wmem.observe(
            "crime:player_theft",
            data={
                "item": item_id,
                "faction": owner_faction,
                "type": "theft",
            },
            game_time=game_time,
            ttl=CRIME_MEMORY_TTL,
        )

        # Is this witness a guard (has AttackConfig + friendly faction)?
        faction = world.get(weid, Faction)
        has_combat = world.has(weid, AttackConfig)
        if has_combat and faction and faction.disposition == "friendly":
            armed_saw = True
            # Armed witness turns hostile immediately
            faction.disposition = "hostile"
            print(f"[CRIME] Armed witness {wname} saw the theft — turning hostile!")
            if player_eid is not None:
                from logic.combat import alert_nearby_faction
                alert_nearby_faction(world, weid, player_eid)
        else:
            brain = world.get(weid, Brain)
            if brain is not None:
                brain.state["crime_flee_until"] = game_time + 20.0

    if armed_saw:
        return "An armed witness saw you steal! They won't let that slide."

    first_name = witness_names[0] if witness_names else "Someone"
    if len(witness_names) == 1:
        return f"{first_name} saw you steal. Word will spread."
    return f"{first_name} and {len(witness_names) - 1} others saw you steal!"


# ── TransferModal callback factory ──────────────────────────────────

def make_theft_callback(world: Any, owner_faction: str,
                        game_time_fn: callable) -> callable:
    """Create an on_steal callback for the TransferModal.

    ``game_time_fn`` is a zero-arg callable returning current game time
    (avoids stale capture).

    The callback is called each time the player takes an item from an
    owned container.  It checks for witnesses and reports the crime.
    Returns a flash message string for the UI, or None for silent theft.
    """
    def on_steal(item_id: str) -> str | None:
        # Find player position
        player_res = None
        for eid, _ in world.all_of(Player):
            pos = world.get(eid, Position)
            if pos:
                player_res = (eid, pos)
            break

        if player_res is None:
            return None

        _player_eid, player_pos = player_res
        gt = game_time_fn()

        witnesses = find_witnesses(
            world, player_pos.zone, player_pos.x, player_pos.y,
        )

        if witnesses:
            return report_theft(world, witnesses, item_id,
                                owner_faction, gt)
        # No witnesses — theft succeeds silently
        print(f"[CRIME] Player stole {item_id} unseen")
        return None

    return on_steal


# ── Query helpers ────────────────────────────────────────────────────

def npc_knows_crimes(world: Any, npc_eid: int,
                     game_time: float) -> bool:
    """Check if an NPC has any fresh crime memories about the player."""
    wmem = world.get(npc_eid, WorldMemory)
    if wmem is None:
        return False
    entries = wmem.query_prefix("crime:", game_time, stale_ok=False)
    return len(entries) > 0


def guard_crime_reaction(world: Any, guard_eid: int,
                         game_time: float) -> bool:
    """Should this guard turn hostile based on crime knowledge?

    Returns True if the guard knows about player crimes and should
    become hostile.  Only applies to NPCs with AttackConfig.
    """
    if not world.has(guard_eid, AttackConfig):
        return False
    faction = world.get(guard_eid, Faction)
    if not faction or faction.disposition == "hostile":
        return False  # already hostile or not faction-affiliated

    return npc_knows_crimes(world, guard_eid, game_time)


# ── Lockpick callback factory ───────────────────────────────────────

def make_lockpick_callback(world: Any, locked_comp,
                           owner_faction: str,
                           game_time_fn: callable) -> callable:
    """Create an on_lockpick callback for the TransferModal.

    Returns a zero-arg callable that attempts to pick the lock.
    Result: ``(bool_success, str_message)``.

    Difficulty determines success chance:
        0 → 100 %, 1 → 75 %, 2 → 50 %, 3 → 25 %

    Picking a lock is always suspicious — witnesses report it as a
    crime regardless of success or failure.
    """
    import random as _rng

    def on_lockpick() -> tuple[bool, str]:
        difficulty = locked_comp.difficulty
        chance = max(0.0, 1.0 - difficulty * 0.25)
        success = _rng.random() < chance

        # --- witness check (same as theft) ---
        player_res = None
        for eid, _ in world.all_of(Player):
            pos = world.get(eid, Position)
            if pos:
                player_res = (eid, pos)
            break

        gt = game_time_fn()
        witness_msg = ""
        if player_res:
            _player_eid, player_pos = player_res
            witnesses = find_witnesses(
                world, player_pos.zone, player_pos.x, player_pos.y,
            )
            if witnesses:
                witness_msg = report_theft(
                    world, witnesses, "(lockpick)", owner_faction, gt,
                )

        if success:
            msg = "Lock picked."
            if witness_msg:
                msg += f"  {witness_msg}"
            return (True, msg)
        else:
            msg = "Failed to pick the lock."
            if witness_msg:
                msg += f"  {witness_msg}"
            return (False, msg)

    return on_lockpick
